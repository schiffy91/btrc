"""Cohesive gpu IR lowering owner."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.gpu import (
    GPU_STATUS_MESSAGES,
    GPU_TRANSFER_FAILURE_MESSAGE,
    GPU_UNKNOWN_STATUS_MESSAGE,
    WGSL_CALL_BUILTINS,
    WGSL_FLOAT_UNARY_BUILTINS,
)
from src.compiler.python.ir.nodes import (
    CType,
    GpuDispatchNames,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRGpuBuffer,
    IRGpuKernel,
    IRGpuShaderModule,
    IRIf,
    IRIndex,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRStmtExpr,
    IRStructDef,
    IRStructField,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    Block,
    BraceInitializer,
    CallExpr,
    FieldAccessExpr,
    FunctionDecl,
    Identifier,
    ListLiteral,
    Param,
    ReturnStmt,
    TypeExpr,
    VarDeclStmt,
)

from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import CallableEvaluationPlan, CallableProvenance, CallLowerer
    from .ownership import (
        CleanupScopeState,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
        OwnershipOperandOrder,
        ProjectionStorageOperand,
    )
    from .session import LoweringSession
    from .storage import StorageLowerer
_WORKGROUP_SIZE = 64
_OUTPUT_CAPACITY_MESSAGE = '"[btrc-gpu] output capacity is smaller than dispatch length\\n"'
_MAX_CHUNK_WORKGROUPS = 65535
OUTPUT_PARAM = "__gpu_output"
OUTPUT_CAPACITY = "__gpu_output_capacity"


@dataclass
class GpuArgumentPlan:
    """Both expression-local and declaration-context materializations."""

    declarations: list[IRVarDecl]
    assignments: list[IRExpr]
    cleanup: list[IRExpr]
    helper_args: list[IRExpr]
    dispatch_length: IRExpr | None


@dataclass(frozen=True, slots=True)
class GpuSourceArgumentPlan:
    """One explicit GPU source operand and its backing-storage contract."""

    source: object
    type_expr: TypeExpr | None
    owned: bool
    pin: bool
    projection_storage: tuple[ProjectionStorageOperand, ...]
    requires_capacity: bool


@dataclass(frozen=True, slots=True)
class GpuSourceArguments:
    """Source-ordered operands stabilized before GPU ABI materialization."""

    declarations: tuple[IRVarDecl, ...]
    assignments: tuple[IRExpr, ...]
    cleanup: tuple[IRExpr, ...]
    values: tuple[IRExpr, ...]
    capacities: tuple[IRExpr | None, ...]
    stabilized: tuple[bool, ...]
    owned: tuple[bool, ...]
    pinned: tuple[bool, ...]


@dataclass
class _SourceSignature:
    params: list[IRParam]
    args: list
    array_lengths: dict[str, str]


@dataclass
class GpuOutputDeclaration:
    setup: list
    array_length: IRExpr | None
    call: IRExpr


@dataclass(frozen=True, slots=True)
class GpuCpuFallbackPlan:
    """Source and ABI facts for an ordinary CPU-fallback body lowering."""

    declaration: FunctionDecl
    source: Block
    item_name: str
    wrapper_name: str
    item_return_type: TypeExpr | None
    item_return_c_type: str
    item_params: tuple[IRParam, ...]
    wrapper_params: tuple[IRParam, ...]
    local_bindings: tuple[str, ...]
    callable_bindings: tuple[Param, ...]
    array_lengths: tuple[tuple[str, str], ...]
    wrapper_body: IRBlock


@dataclass(frozen=True, slots=True)
class GpuDispatchSpec:
    kernel: IRGpuKernel
    declaration: FunctionDecl
    names: GpuDispatchNames
    helper_name: str
    uniform_struct: str
    has_output: bool
    total_bindings: int
    buffers_by_name: tuple[tuple[str, IRGpuBuffer], ...]
    result_elem_type: str
    cpu_fallback: str
    helper_parameters: tuple[IRParam, ...]
    parameter_c_names: tuple[tuple[str, str], ...]
    dispatch_length_value: IRExpr
    cpu_argument_values: tuple[IRExpr, ...]


@dataclass
class GpuOutputTarget:
    declarations: list[IRVarDecl]
    assignments: list[IRExpr]
    cleanup: list[IRExpr]
    data: IRExpr
    capacity: IRExpr
    result: IRExpr


class GpuLowerer:
    """Own gpu lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cleanup_scope: CleanupScopeState,
        operand_order: OwnershipOperandOrder,
        calls: CallLowerer,
        storage: StorageLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cleanup_scope = cleanup_scope
        self._operand_order = operand_order
        self._calls = calls
        self._storage = storage
        self._gpu_kernels: dict[str, IRGpuKernel] = {}
        self._gpu_cpu_array_lengths: dict[str, str] = {}
        self._gpu_cpu_item_output_type = None

    def cpu_array_length(self, name: str) -> str | None:
        """Return the active CPU-fallback length binding for one GPU array."""

        return self._gpu_cpu_array_lengths.get(name)

    def emit_gpu_kernel(self, decl: FunctionDecl) -> None:
        """Retain a typed shader body and host-dispatch metadata in IR."""
        name = decl.name
        if name in self._gpu_kernels:
            return
        param_buffers: list[IRGpuBuffer] = []
        uniform_params: list[tuple[str, object]] = []
        bool_uniform_params: list[str] = []
        binding = 0
        for param in decl.params:
            if param.type and param.type.is_array:
                param_buffers.append(
                    IRGpuBuffer(name=param.name, elem_type=param.type, access="read_write", binding=binding)
                )
                binding += 1
            else:
                semantic_type = param.type or TypeExpr(base="int")
                if param.type and param.type.base == "bool":
                    bool_uniform_params.append(param.name)
                uniform_params.append((param.name, semantic_type))
        output_buffer = None
        ret = decl.return_type
        if ret and ret.base != "void" and ret.is_array:
            output_buffer = IRGpuBuffer(name="_output", elem_type=ret, access="read_write", binding=binding)
        shader_module = IRGpuShaderModule(
            body=decl.body,
            node_types=self._analyzed.node_types,
            output_type=ret,
            bool_uniform_params=bool_uniform_params,
        )
        uniform_binding = (
            output_buffer.binding + 1 if output_buffer else (param_buffers[-1].binding + 1 if param_buffers else 0)
        )
        kernel = IRGpuKernel(
            name=name,
            shader_module=shader_module,
            workgroup_size=_WORKGROUP_SIZE,
            param_buffers=param_buffers,
            output_buffer=output_buffer,
            uniform_params=uniform_params,
            status_binding=uniform_binding + 1,
        )
        self._gpu_kernels[name] = kernel
        self._session.module.gpu_kernels.append(kernel)

    def plan_gpu_cpu_fallback(self, decl: FunctionDecl, provenance: CallableProvenance) -> GpuCpuFallbackPlan | None:
        """Describe a GPU CPU fallback without traversing its source body."""
        if decl.body is None:
            return None
        signature = self._source_signature(
            decl,
            provenance,
        )
        output_type = GpuLowerer._output_element_type(decl)
        item_name = f"{decl.name}__gpuitem"
        wrapper_name = f"{decl.name}__gpucpu"
        item_return_type = output_type or decl.return_type
        item_return_c_type = self._types.render(item_return_type) if item_return_type else "void"
        item_params = (*signature.params, IRParam(c_type=CType(text="int"), name="__gid"))
        wrapper_params = list(signature.params)
        if output_type is not None:
            wrapper_params.extend(
                [
                    IRParam(c_type=CType(text=f"{item_return_c_type}*"), name=OUTPUT_PARAM),
                    IRParam(c_type=CType(text="int"), name=OUTPUT_CAPACITY),
                ]
            )
        wrapper_params.append(IRParam(c_type=CType(text="int"), name="__gpu_n"))
        return GpuCpuFallbackPlan(
            declaration=decl,
            source=decl.body,
            item_name=item_name,
            wrapper_name=wrapper_name,
            item_return_type=item_return_type,
            item_return_c_type=item_return_c_type,
            item_params=tuple(item_params),
            wrapper_params=tuple(wrapper_params),
            local_bindings=tuple(parameter.name for parameter in decl.params),
            callable_bindings=tuple(decl.params),
            array_lengths=tuple(signature.array_lengths.items()),
            wrapper_body=GpuLowerer._wrapper_body(item_name, signature.args, output_type is not None),
        )

    @contextmanager
    def gpu_cpu_item_scope(self, plan: GpuCpuFallbackPlan):
        """Install the bounded GPU-item facts needed during ordinary body lowering."""
        previous_index = self._session.gpu_cpu_index
        previous_lengths = self._gpu_cpu_array_lengths
        previous_output = self._gpu_cpu_item_output_type
        self._session.gpu_cpu_index = "__gid"
        self._gpu_cpu_array_lengths = dict(plan.array_lengths)
        self._gpu_cpu_item_output_type = GpuLowerer._output_element_type(plan.declaration)
        try:
            yield
        finally:
            self._session.gpu_cpu_index = previous_index
            self._gpu_cpu_array_lengths = previous_lengths
            self._gpu_cpu_item_output_type = previous_output

    def materialize_gpu_cpu_fallback(
        self,
        plan: GpuCpuFallbackPlan,
        body: IRBlock,
    ) -> None:
        """Install a CPU fallback after the ordinary statement owner lowers it."""
        self._session.module.function_decls.extend(
            [
                IRFunctionDecl(
                    name=plan.item_name,
                    return_type=CType(text=plan.item_return_c_type),
                    params=list(plan.item_params),
                    is_static=True,
                ),
                IRFunctionDecl(
                    name=plan.wrapper_name,
                    return_type=CType(text="void"),
                    params=list(plan.wrapper_params),
                    is_static=True,
                ),
            ]
        )
        self._session.module.function_defs.extend(
            [
                IRFunctionDef(
                    name=plan.item_name,
                    return_type=CType(text=plan.item_return_c_type),
                    params=list(plan.item_params),
                    body=body,
                    is_static=True,
                ),
                IRFunctionDef(
                    name=plan.wrapper_name,
                    return_type=CType(text="void"),
                    params=list(plan.wrapper_params),
                    body=plan.wrapper_body,
                    is_static=True,
                ),
            ]
        )

    def is_direct_gpu_call(self, node, provenance: CallableProvenance) -> bool:
        """Whether an identifier kernel call is not shadowed lexically."""
        from src.compiler.python.syntax.ast.generated import Identifier

        if not isinstance(node.callee, Identifier):
            return False
        name = node.callee.name
        return bool(
            name in self._gpu_kernels
            and (not self._session.local_is_declared(name))
            and (name not in self._analyzed.global_var_types)
            and (provenance.environment(name) is None)
        )

    def materialize_direct_gpu_call(
        self,
        node: CallExpr,
        lowered_arguments: GpuSourceArguments,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Materialize one kernel call from operands lowered by ExpressionLowerer."""
        if not self.is_direct_gpu_call(node, provenance):
            raise CodegenError("direct GPU call materialized for a shadowed or unknown target")
        return self._gpu_dispatch_lower_gpu_call(
            node.callee.name,
            node.args,
            GpuLowerer._arg_names(node),
            lowered_arguments,
            provenance,
            call=node,
        )

    def plan_source_arguments(
        self,
        call: CallExpr,
        provenance: CallableProvenance,
    ) -> tuple[GpuSourceArgumentPlan, ...]:
        """Describe explicit GPU operands before expression lowering."""
        if not self.is_direct_gpu_call(call, provenance):
            raise CodegenError("GPU source arguments require a direct kernel call")
        declaration = self._analyzed.function_table[call.callee.name]
        source_flow = provenance.plan_evaluation(call.args)
        bindings, _bound_nodes, argument_types, owned_flags, pin_flags = self.plan_gpu_argument_bindings(
            declaration,
            call.args,
            GpuLowerer._arg_names(call),
            provenance,
            flow=source_flow,
        )
        effects = [
            bool(is_default or self._ownership.has_observable_effect(argument))
            for _index, argument, is_default in bindings
        ]
        plans = []
        for binding_index, ((parameter_index, argument, is_default), argument_type) in enumerate(
            zip(bindings, argument_types)
        ):
            if is_default:
                continue
            parameter = declaration.params[parameter_index]
            entry = source_flow.entries.get(id(argument), source_flow.incoming)
            with provenance.at_flow(entry):
                projection_storage = self._ownership.projection_storage_operands(
                    argument,
                    provenance,
                    call=call,
                    parameter_index=parameter_index,
                    has_later_effects=any(effects[binding_index + 1 :]),
                )
            plans.append(
                GpuSourceArgumentPlan(
                    source=argument,
                    type_expr=argument_type,
                    owned=owned_flags[binding_index],
                    pin=pin_flags[binding_index],
                    projection_storage=projection_storage,
                    requires_capacity=bool(
                        parameter.type and parameter.type.is_array and not GpuLowerer.is_heap_collection(argument_type)
                    ),
                )
            )
        if len(plans) != len(call.args):
            raise CodegenError(f"@gpu call '{declaration.name}' arguments were not planned exactly once")
        return tuple(plans)

    def source_array_capacity(
        self,
        source,
        lowered: IRExpr,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Derive a fixed-array extent before its stabilized value decays."""
        return self.bare_array_argument_length(source, lowered, provenance)

    def argument_c_type(self, parameter_type, argument_type) -> str:
        effective = argument_type or parameter_type
        return self._types.render(effective) if effective is not None else "int"

    @staticmethod
    def buffer_length_name(parameter_name: str) -> str:
        return f"__gpu_len_{parameter_name}"

    def plan_gpu_argument_bindings(
        self,
        declaration,
        ast_args,
        arg_names,
        provenance: CallableProvenance,
        *,
        flow: CallableEvaluationPlan | None = None,
    ):
        bindings = []
        seen = set()
        for slot, argument, is_default in self._calls.bind_arg_nodes_to_params(declaration.params, ast_args, arg_names):
            if slot is None or slot >= len(declaration.params):
                raise CodegenError(f"@gpu call '{declaration.name}' contains an unknown argument")
            if slot in seen:
                raise CodegenError(f"duplicate @gpu argument for parameter '{declaration.params[slot].name}'")
            seen.add(slot)
            bindings.append((slot, argument, is_default))
        types = [
            self._session.type_of(argument) or declaration.params[index].type
            for index, argument, _is_default in bindings
        ]
        owned = []
        for (_index, argument, _is_default), type_expr in zip(bindings, types):
            if not GpuLowerer._heap_collection(type_expr):
                owned.append(False)
                continue
            entry = flow.entries.get(id(argument)) if flow is not None else None
            if entry is None:
                result_owned = self._owns_result(argument, provenance)
            else:
                with provenance.at_flow(entry):
                    result_owned = self._owns_result(argument, provenance)
            owned.append(bool(result_owned))
        pins = self._operand_order.source_order_pin_flags(
            [argument for _index, argument, _is_default in bindings], types, owned
        )
        return (bindings, self._calls.bound_nodes_by_parameter(declaration.params, bindings), types, owned, pins)

    @staticmethod
    def _heap_collection(type_expr) -> bool:
        return bool(
            type_expr is not None
            and getattr(type_expr, "generic_args", None)
            and (type_expr.base in ("Array", "Vector"))
        )

    @staticmethod
    def default_array_dependency(params, param_index, argument):
        """Find an earlier array parameter referenced by a simple default."""
        from src.compiler.python.syntax.ast.generated import Identifier

        if not isinstance(argument, Identifier):
            return None
        for index, parameter in enumerate(params[:param_index]):
            if parameter.name == argument.name and parameter.type is not None and parameter.type.is_array:
                return index
        return None

    def capture_collection_view(self, parameter, stable, declarations, assignments):
        """Capture a collection's view before later arguments can replace it."""
        data_name = self._session.fresh_temp("__gpu_data")
        length_name = self._session.fresh_temp("__gpu_len")
        data_declaration = IRVarDecl(c_type=CType(text=self._types.render(parameter.type)), name=data_name)
        length_declaration = IRVarDecl(c_type=CType(text="int"), name=length_name)
        declarations.extend((data_declaration, length_declaration))
        self._session.record_declaration(data_declaration)
        self._session.record_declaration(length_declaration)
        data = IRVar(name=data_name)
        length = IRVar(name=length_name)
        assignments.extend(
            (
                IRBinOp(left=data, op="=", right=IRFieldAccess(obj=stable, field="data", arrow=True)),
                IRBinOp(left=length, op="=", right=IRFieldAccess(obj=stable, field="len", arrow=True)),
            )
        )
        return (data, length)

    def capture_array_length(
        self,
        expression,
        lowered,
        declarations,
        assignments,
        provenance: CallableProvenance,
    ):
        """Snapshot fixed-array capacity beside its data-pointer snapshot."""
        name = self._session.fresh_temp("__gpu_len")
        declaration = IRVarDecl(c_type=CType(text="int"), name=name)
        declarations.append(declaration)
        self._session.record_declaration(declaration)
        length = IRVar(name=name)
        assignments.append(
            IRBinOp(
                left=length,
                op="=",
                right=self.bare_array_argument_length(expression, lowered, provenance),
            )
        )
        return length

    def lower_default_argument(
        self,
        call,
        declaration,
        param_index,
        bound_nodes,
        stable_overrides,
        parameter_values,
        provenance: CallableProvenance,
    ):
        """Evaluate a default with earlier parameters in their kernel ABI form."""
        if call is None:
            raise CodegenError("default GPU argument requires its source call")
        overrides = dict(stable_overrides)
        for index, node in enumerate(bound_nodes[:param_index]):
            if node is not None and index in parameter_values:
                overrides[id(node)] = parameter_values[index]
        return self._calls.materialize_default_call(
            call,
            declaration.params,
            param_index,
            bound_nodes,
            overrides,
            provenance,
        )

    @staticmethod
    def inherited_array_length(declaration, param_index, argument, *, is_default, lengths):
        """Reuse the snapshot belonging to a referenced earlier parameter."""
        if not is_default:
            return None
        dependency = GpuLowerer.default_array_dependency(declaration.params, param_index, argument)
        return lengths.get(dependency) if dependency is not None else None

    def argument_lifetime_cleanup(self, declaration, stable, type_expr, c_type, *, pin):
        """Protect an owned or pinned collection through dispatch."""
        declarations = []
        prefix = [self._lifetime.retain_value(stable, type_expr)] if pin else []
        self._lifetime.protect_temporary(
            declaration,
            type_expr,
            declarations,
            prefix,
            "__btrc_gpu_arg_cleanup",
            active=self._cleanup_scope.exception_cleanup_active(),
        )
        suffix = self._lifetime.release_and_clear(stable, type_expr, declarations, c_type)
        return (declarations, prefix, suffix)

    def _owns_result(self, expression, provenance: CallableProvenance) -> bool:
        return self._ownership.lowered_result_is_owned(expression, provenance=provenance)

    def _override_value(self, expression):
        return self._session.owning_overrides.get(id(expression))

    def prepare_gpu_arguments(
        self,
        declaration: FunctionDecl,
        ast_args: list,
        arg_names: list[str],
        lowered_arguments: GpuSourceArguments,
        provenance: CallableProvenance,
        *,
        call=None,
    ) -> GpuArgumentPlan:
        """Evaluate in source order, then expose values in parameter order."""
        ir_args = lowered_arguments.values
        if len(ast_args) != len(ir_args):
            raise CodegenError(f"@gpu call '{declaration.name}' arguments were not lowered exactly once")
        if len(lowered_arguments.capacities) != len(ir_args):
            raise CodegenError(f"@gpu call '{declaration.name}' capacities were not planned exactly once")
        if len(lowered_arguments.stabilized) != len(ir_args):
            raise CodegenError(f"@gpu call '{declaration.name}' stabilization was not planned exactly once")
        if len(lowered_arguments.owned) != len(ir_args):
            raise CodegenError(f"@gpu call '{declaration.name}' ownership was not planned exactly once")
        if len(lowered_arguments.pinned) != len(ir_args):
            raise CodegenError(f"@gpu call '{declaration.name}' pinning was not planned exactly once")
        declarations: list[IRVarDecl] = list(lowered_arguments.declarations)
        assignments: list[IRExpr] = list(lowered_arguments.assignments)
        cleanup: list[IRExpr] = []
        values: dict[int, IRExpr] = {}
        lengths: dict[int, IRExpr] = {}
        stable_overrides: dict[int, IRExpr] = {}
        bindings, bound_nodes, argument_types, owned_flags, pin_flags = self.plan_gpu_argument_bindings(
            declaration, ast_args, arg_names, provenance
        )
        source_index = 0
        for binding_index, (index, ast_argument, is_default) in enumerate(bindings):
            parameter = declaration.params[index]
            if is_default:
                argument = self._override_value(ast_argument)
                if argument is None:
                    argument = self.lower_default_argument(
                        call,
                        declaration,
                        index,
                        bound_nodes,
                        stable_overrides,
                        values,
                        provenance,
                    )
            else:
                argument = ir_args[source_index]
                source_capacity = lowered_arguments.capacities[source_index]
                source_stabilized = lowered_arguments.stabilized[source_index]
                source_owned = lowered_arguments.owned[source_index]
                source_pinned = lowered_arguments.pinned[source_index]
                source_index += 1
            argument_type = argument_types[binding_index]
            temp = self._session.fresh_temp("__gpu_arg")
            c_type_text = self.argument_c_type(parameter.type, argument_type)
            declaration_node = IRVarDecl(c_type=CType(text=c_type_text), name=temp)
            declarations.append(declaration_node)
            self._session.record_declaration(declaration_node)
            assignments.append(IRBinOp(left=IRVar(name=temp), op="=", right=argument))
            stable = IRVar(name=temp)
            stable_overrides[id(ast_argument)] = stable
            owned = bool(
                (owned_flags[binding_index] if is_default else source_owned) and (is_default or not source_stabilized)
            )
            pinned = bool(
                (is_default or not source_stabilized)
                and GpuLowerer.is_heap_collection(argument_type)
                and (pin_flags[binding_index] if is_default else source_pinned)
            )
            if owned or pinned:
                owned_declarations, owned_prefix, owned_suffix = self.argument_lifetime_cleanup(
                    declaration_node, stable, argument_type, c_type_text, pin=pinned
                )
                declarations.extend(owned_declarations)
                assignments.extend(owned_prefix)
                cleanup.extend(owned_suffix)
            values[index] = stable
            if parameter.type and parameter.type.is_array:
                if GpuLowerer.is_heap_collection(argument_type):
                    data, length = self.capture_collection_view(
                        parameter,
                        stable,
                        declarations,
                        assignments,
                    )
                else:
                    data = stable
                    length = GpuLowerer.inherited_array_length(
                        declaration, index, ast_argument, is_default=is_default, lengths=lengths
                    )
                    if length is None:
                        if not is_default and source_capacity is not None:
                            length = source_capacity
                        else:
                            length = self.capture_array_length(
                                ast_argument,
                                argument,
                                declarations,
                                assignments,
                                provenance,
                            )
                values[index] = data
                lengths[index] = length
        if source_index != len(ir_args):
            raise CodegenError(f"@gpu call '{declaration.name}' arguments were not bound exactly once")
        cleanup.extend(lowered_arguments.cleanup)
        helper_args: list[IRExpr] = []
        dispatch_length = None
        for index, parameter in enumerate(declaration.params):
            if index not in values:
                raise CodegenError(f"missing required argument for parameter '{parameter.name}'")
            helper_args.append(values[index])
            if parameter.type and parameter.type.is_array:
                helper_args.append(lengths[index])
                if dispatch_length is None:
                    dispatch_length = lengths[index]
        return GpuArgumentPlan(
            declarations=declarations,
            assignments=assignments,
            cleanup=cleanup,
            helper_args=helper_args,
            dispatch_length=dispatch_length or IRLiteral(text="1"),
        )

    @staticmethod
    def is_heap_collection(argument_type) -> bool:
        return bool(
            argument_type is not None
            and getattr(argument_type, "generic_args", None)
            and (argument_type.base in ("Array", "Vector"))
        )

    @staticmethod
    def bare_array_length(argument: IRExpr) -> IRExpr:
        return IRBinOp(
            left=IRSizeof(operand=argument),
            op="/",
            right=IRSizeof(operand=IRIndex(obj=argument, index=IRLiteral(text="0"))),
        )

    def bare_array_argument_length(
        self,
        argument,
        lowered_argument: IRExpr | None,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Preserve a real C array's extent before its value decays to a pointer."""
        if isinstance(argument, Identifier):
            local_status = self._storage.local_c_array_status(argument.name)
            logical_length = self._storage.local_gpu_array_length(argument.name)
            if logical_length is not None:
                return logical_length
            if local_status is True or (local_status is None and self.backed_global_array(argument.name)):
                return GpuLowerer.bare_array_length(
                    IRVar(name=self._ownership.source_binding_c_name(argument.name, provenance))
                )
        argument_type = self._session.type_of(argument)
        if (
            isinstance(argument, FieldAccessExpr)
            and lowered_argument is not None
            and (argument_type is not None)
            and (argument_type.pointer_depth == 0)
            and argument_type.is_array
            and (argument_type.array_size is not None or self.backed_static_field(argument))
        ):
            return GpuLowerer.bare_array_length(lowered_argument)
        name = argument.name if isinstance(argument, Identifier) else "expression"
        raise CodegenError(f"GPU array argument '{name}' has no provable capacity in this scope")

    def backed_global_array(self, name: str) -> bool:
        """Whether a file-scope source array has complete physical C backing."""
        global_type = self._analyzed.global_var_types.get(name)
        if global_type is None or not global_type.is_array:
            return False
        if global_type.array_size is not None:
            return True
        return any(
            isinstance(declaration, VarDeclStmt)
            and declaration.name == name
            and isinstance(declaration.initializer, (BraceInitializer, ListLiteral))
            for declaration in self._analyzed.program.declarations
        )

    def backed_static_field(self, target) -> bool:
        """Whether a class-access array field owns aggregate/fixed backing."""
        if not isinstance(target, FieldAccessExpr) or not isinstance(target.obj, Identifier):
            return False
        if self._session.local_is_declared(target.obj.name):
            return False
        owner = self._analyzed.class_table.get(target.obj.name)
        field = owner.static_fields.get(target.field) if owner is not None else None
        return bool(
            field
            and field.type.is_array
            and (field.type.array_size is not None or isinstance(field.initializer, (BraceInitializer, ListLiteral)))
        )

    def lower_gpu_cpu_builtin(self, name: str, ast_args: list, ir_args: list):
        if not self._session.gpu_cpu_index:
            return None
        if name == "gpu_id" and name not in self._analyzed.function_table:
            return IRVar(name=self._session.gpu_cpu_index)
        if name not in WGSL_CALL_BUILTINS:
            return None
        argument_types = [self._session.type_of(argument) for argument in ast_args]
        base = argument_types[0].base if argument_types and argument_types[0] is not None else "float"
        if name == "abs":
            return IRCall(callee="fabsf" if base == "float" else "abs", args=ir_args)
        if name in WGSL_FLOAT_UNARY_BUILTINS:
            return IRCall(callee=f"{name}f", args=ir_args)
        if name == "pow":
            return IRCall(callee="powf", args=ir_args)
        if name in ("min", "max"):
            if base == "float":
                return IRCall(callee=f"f{name}f", args=ir_args)
            return GpuLowerer._integer_extreme(name, ir_args[0], ir_args[1])
        if name == "clamp":
            if base == "float":
                return IRCall(callee="fminf", args=[IRCall(callee="fmaxf", args=ir_args[:2]), ir_args[2]])
            return GpuLowerer._integer_extreme(
                "min", GpuLowerer._integer_extreme("max", ir_args[0], ir_args[1]), ir_args[2]
            )
        return None

    def is_gpu_cpu_builtin(self, name: str) -> bool:
        """Whether CPU fallback lowering owns this source builtin call."""
        return bool(
            self._session.gpu_cpu_index
            and (name in WGSL_CALL_BUILTINS or (name == "gpu_id" and name not in self._analyzed.function_table))
        )

    @staticmethod
    def _integer_extreme(name: str, left, right):
        operator = "<" if name == "min" else ">"
        return IRTernary(condition=IRBinOp(left=left, op=operator, right=right), true_expr=left, false_expr=right)

    def gpu_cpu_item_return_active(self) -> bool:
        """Whether returns currently belong to an array-valued GPU item body."""
        return self._gpu_cpu_item_output_type is not None

    def materialize_gpu_cpu_item_return(
        self,
        node: ReturnStmt,
        lowered_value: IRExpr | None,
    ) -> list[IRReturn]:
        """Materialize an already-lowered worker result at the GPU item ABI."""
        output_type = self._gpu_cpu_item_output_type
        if output_type is None:
            raise CodegenError("GPU item return materialized outside an output-kernel body")
        if node.value is None:
            raise CodegenError("array-returning @gpu worker cannot return without a value")
        if lowered_value is None:
            raise CodegenError("GPU item return value was not materialized")
        value_type = self._session.type_of(node.value)
        if value_type is not None and value_type.is_array:
            if not isinstance(node.value, Identifier):
                raise CodegenError("whole-array @gpu return must name a source buffer")
            length_name = self._gpu_cpu_array_lengths.get(node.value.name)
            if length_name is None:
                raise CodegenError(f"whole-array @gpu return '{node.value.name}' has no source length")
            self._session.require_helper("__btrc_gpu_index_check")
            value = IRIndex(
                obj=lowered_value,
                index=IRCall(
                    callee="__btrc_gpu_index_check",
                    args=[IRVar(name="__gid"), IRVar(name=length_name)],
                    helper_ref="__btrc_gpu_index_check",
                ),
            )
        else:
            value = lowered_value
        return [IRReturn(value=value)]

    def _source_signature(self, decl: FunctionDecl, provenance: CallableProvenance) -> _SourceSignature:
        params = []
        args = []
        lengths = {}
        for parameter in decl.params:
            params.append(provenance.lower_source_param(parameter))
            args.append(IRVar(name=provenance.source_binding_c_name(parameter.name)))
            if parameter.type and parameter.type.is_array:
                length_name = GpuLowerer.buffer_length_name(parameter.name)
                params.append(IRParam(c_type=CType(text="int"), name=length_name))
                args.append(IRVar(name=length_name))
                lengths[parameter.name] = length_name
        return _SourceSignature(params=params, args=args, array_lengths=lengths)

    @staticmethod
    def _output_element_type(decl: FunctionDecl):
        return_type = decl.return_type
        if return_type is None or return_type.base == "void":
            return None
        from src.compiler.python.analyzer.types import TypeSystem

        return TypeSystem.strip_outer_storage(return_type, array=True)

    @staticmethod
    def _wrapper_body(item_name: str, source_args: list, has_output: bool) -> IRBlock:
        gid = IRVar(name="__gid")
        item_call = IRCall(callee=item_name, args=[*source_args, gid])
        if has_output:
            loop_statement = IRAssign(target=IRIndex(obj=IRVar(name=OUTPUT_PARAM), index=gid), value=item_call)
            prefix = [GpuLowerer._output_capacity_guard()]
        else:
            loop_statement = IRExprStmt(expr=item_call)
            prefix = []
        loop = IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name="__gid", init=IRLiteral(text="0")),
            condition=IRBinOp(left=gid, op="<", right=IRVar(name="__gpu_n")),
            update=IRUnaryOp(op="++", operand=gid, prefix=False),
            body=IRBlock(stmts=[loop_statement]),
        )
        return IRBlock(stmts=[*prefix, loop])

    @staticmethod
    def _output_capacity_guard():
        invalid = IRBinOp(
            left=IRUnaryOp(op="!", operand=IRVar(name=OUTPUT_PARAM)),
            op="||",
            right=IRBinOp(left=IRVar(name=OUTPUT_CAPACITY), op="<", right=IRVar(name="__gpu_n")),
        )
        return IRIf(
            condition=IRBinOp(
                left=IRBinOp(left=IRVar(name="__gpu_n"), op=">", right=IRLiteral(text="0")), op="&&", right=invalid
            ),
            then_block=IRBlock(
                stmts=[
                    IRExprStmt(
                        expr=IRCall(
                            callee="fputs", args=[IRLiteral(text=_OUTPUT_CAPACITY_MESSAGE), IRVar(name="stderr")]
                        )
                    ),
                    IRExprStmt(expr=IRCall(callee="abort", args=[])),
                ]
            ),
        )

    def _gpu_dispatch_lower_gpu_call(
        self,
        function_name: str,
        ast_args: list,
        arg_names: list[str],
        ir_args: list[IRExpr],
        provenance: CallableProvenance,
        *,
        call=None,
    ) -> IRExpr:
        """Lower a void kernel call or reject an unsafe array-valued context."""
        kernel = self._gpu_kernels[function_name]
        if kernel.output_buffer is not None:
            raise CodegenError(
                f"array-returning @gpu call '{function_name}' is only valid as an array declaration initializer or direct array assignment"
            )
        spec, arguments = self._prepare_site(
            function_name,
            ast_args,
            arg_names,
            ir_args,
            provenance,
            call=call,
        )
        call = IRCall(callee=spec.helper_name, args=arguments.helper_args)
        return GpuLowerer._expression_local_call(arguments, call)

    def output_gpu_call_name(self, expression, provenance: CallableProvenance) -> str | None:
        if not (isinstance(expression, CallExpr) and isinstance(expression.callee, Identifier)):
            return None
        if not self.is_direct_gpu_call(expression, provenance):
            return None
        name = expression.callee.name
        kernel = self._gpu_kernels.get(name)
        if kernel is None or kernel.output_buffer is None:
            return None
        return name

    def lower_gpu_output_declaration(
        self,
        call: CallExpr,
        target: IRExpr,
        lowered_arguments: GpuSourceArguments,
        provenance: CallableProvenance,
    ) -> GpuOutputDeclaration:
        """Lower an output kernel used to initialize a C array declaration."""
        name = self.output_gpu_call_name(call, provenance)
        if name is None:
            raise CodegenError("expected an array-returning @gpu call")
        spec, arguments = self._prepare_site(
            name,
            call.args,
            GpuLowerer._arg_names(call),
            lowered_arguments,
            provenance,
            call=call,
        )
        helper_call = IRCall(
            callee=spec.helper_name, args=[*arguments.helper_args, target, GpuLowerer.declaration_capacity(target)]
        )
        return GpuOutputDeclaration(
            setup=GpuLowerer._statement_setup(arguments),
            array_length=arguments.dispatch_length,
            call=GpuLowerer._call_with_cleanup(arguments, helper_call),
        )

    def lower_gpu_output_assignment(
        self,
        call: CallExpr,
        ast_target,
        target: IRExpr,
        target_capacity: IRExpr | None,
        lowered_arguments: GpuSourceArguments,
        provenance: CallableProvenance,
        *,
        result_owned: bool,
    ) -> IRExpr:
        """Lower direct output readback through an existing array lvalue."""
        name = self.output_gpu_call_name(call, provenance)
        if name is None:
            raise CodegenError("expected an array-returning @gpu call")
        output = self.assignment_target(
            ast_target,
            target,
            target_capacity,
            provenance,
            result_owned=result_owned,
        )
        spec, arguments = self._prepare_site(
            name,
            call.args,
            GpuLowerer._arg_names(call),
            lowered_arguments,
            provenance,
            call=call,
        )
        arguments.declarations[:0] = output.declarations
        arguments.assignments[:0] = output.assignments
        arguments.cleanup.extend(output.cleanup)
        helper_call = IRCall(callee=spec.helper_name, args=[*arguments.helper_args, output.data, output.capacity])
        return GpuLowerer._expression_local_call(arguments, helper_call, result=output.result)

    def _prepare_site(
        self,
        function_name: str,
        ast_args: list,
        arg_names: list[str],
        ir_args: GpuSourceArguments,
        provenance: CallableProvenance,
        *,
        call=None,
    ) -> tuple[GpuDispatchSpec, GpuArgumentPlan]:
        kernel = self._gpu_kernels[function_name]
        declaration = self._analyzed.function_table[function_name]
        result_elem_type = self._result_element_type(declaration) if kernel.output_buffer is not None else ""
        prefix = self._session.fresh_temp("__gpu_dispatch")
        parameter_c_names = tuple(
            (parameter.name, provenance.source_binding_c_name(parameter.name)) for parameter in declaration.params
        )
        helper_parameters: list[IRParam] = []
        cpu_arguments: list[IRExpr] = []
        dispatch_length: IRExpr = IRLiteral(text="1")
        found_dispatch_length = False
        for parameter in declaration.params:
            helper_parameters.append(provenance.lower_source_param(parameter))
            c_name = provenance.source_binding_c_name(parameter.name)
            cpu_arguments.append(IRVar(name=c_name))
            if parameter.type and parameter.type.is_array:
                length_name = GpuLowerer.buffer_length_name(parameter.name)
                helper_parameters.append(IRParam(c_type=CType(text="int"), name=length_name))
                cpu_arguments.append(IRVar(name=length_name))
                if not found_dispatch_length:
                    dispatch_length = IRVar(name=length_name)
                    found_dispatch_length = True
        if kernel.output_buffer is not None:
            helper_parameters.extend(
                [
                    IRParam(c_type=CType(text=f"{result_elem_type}*"), name=OUTPUT_PARAM),
                    IRParam(c_type=CType(text="int"), name=OUTPUT_CAPACITY),
                ]
            )
        names = GpuDispatchNames(prefix)
        spec = GpuDispatchSpec(
            kernel=kernel,
            declaration=declaration,
            names=names,
            helper_name=names.local("run"),
            uniform_struct=names.local("uniforms_type"),
            has_output=kernel.output_buffer is not None,
            total_bindings=len(kernel.param_buffers) + int(kernel.output_buffer is not None) + 2,
            buffers_by_name=tuple((buffer.name, buffer) for buffer in kernel.param_buffers),
            result_elem_type=result_elem_type,
            cpu_fallback=f"{function_name}__gpucpu",
            helper_parameters=tuple(helper_parameters),
            parameter_c_names=parameter_c_names,
            dispatch_length_value=dispatch_length,
            cpu_argument_values=tuple(cpu_arguments),
        )
        arguments = self.prepare_gpu_arguments(
            declaration,
            ast_args,
            arg_names,
            ir_args,
            provenance,
            call=call,
        )
        self._register_dispatch_helper(spec, provenance)
        return (spec, arguments)

    def _register_dispatch_helper(self, spec: GpuDispatchSpec, provenance: CallableProvenance) -> None:
        self._session.require_runtime_header("btrc_gpu.h")
        uniform_types = dict(spec.kernel.uniform_params)
        uniform_fields = [
            IRStructField(
                c_type=CType(text=GpuLowerer.host_scalar_type(uniform_types[parameter.name], uniform=True)),
                name=provenance.source_binding_c_name(parameter.name),
            )
            for parameter in spec.declaration.params
            if not (parameter.type and parameter.type.is_array)
        ]
        uniform_fields.extend(
            IRStructField(c_type=CType(text="int"), name=GpuLowerer.buffer_length_name(buffer.name))
            for buffer in spec.kernel.param_buffers
        )
        uniform_fields.extend(
            [
                IRStructField(c_type=CType(text="int"), name="__gpu_off"),
                IRStructField(c_type=CType(text="int"), name="__gpu_n"),
            ]
        )
        self._session.module.struct_defs.append(IRStructDef(name=spec.uniform_struct, fields=uniform_fields))
        body = IRBlock(
            stmts=[
                *GpuLowerer.initial_state(spec),
                *GpuLowerer.storage_buffers(spec),
                *GpuLowerer.uniforms_and_pipeline(spec),
                *GpuLowerer.bind_group(spec),
                *GpuLowerer.execution_and_recovery(spec),
            ]
        )
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=spec.helper_name,
                return_type=CType(text="void"),
                params=list(spec.helper_parameters),
                body=body,
                is_static=True,
            )
        )

    @staticmethod
    def _expression_local_call(
        arguments: GpuArgumentPlan,
        call: IRCall,
        *,
        result: IRExpr | None = None,
    ) -> IRExpr:
        expressions = [*arguments.assignments, call, *arguments.cleanup]
        if result is not None:
            expressions.append(result)
        if not arguments.declarations:
            return expressions[0] if len(expressions) == 1 else IRCommaExpr(expressions=expressions)
        return IRStmtExpr(
            stmts=arguments.declarations,
            result=IRCommaExpr(expressions=expressions),
        )

    @staticmethod
    def _statement_setup(arguments: GpuArgumentPlan) -> list:
        return [*arguments.declarations, *(IRExprStmt(expr=expression) for expression in arguments.assignments)]

    @staticmethod
    def _call_with_cleanup(arguments: GpuArgumentPlan, call: IRCall) -> IRExpr:
        if not arguments.cleanup:
            return call
        return IRCommaExpr(expressions=[call, *arguments.cleanup])

    def _result_element_type(self, declaration) -> str:
        from src.compiler.python.analyzer.types import TypeSystem

        return self._types.render(TypeSystem.strip_outer_storage(declaration.return_type, array=True))

    @staticmethod
    def _arg_names(call: CallExpr) -> list[str]:
        names = list(getattr(call, "arg_names", []) or [])
        if len(names) < len(call.args):
            names.extend([""] * (len(call.args) - len(names)))
        return names[: len(call.args)]

    @staticmethod
    def host_scalar_type(type_expr, *, uniform: bool = False) -> str:
        """Map semantic GPU scalar storage to its host-side C spelling."""
        base = getattr(type_expr, "base", type_expr)
        if uniform and base in ("bool", "u32"):
            return "uint32_t"
        return {
            "float": "float",
            "f32": "float",
            "int": "int",
            "i32": "int",
            "uint": "uint32_t",
            "u32": "uint32_t",
            "bool": "bool",
        }.get(base, "float")

    @staticmethod
    def execution_and_recovery(spec: GpuDispatchSpec) -> list:
        names = spec.names
        statements = [
            IRVarDecl(
                c_type=CType(text="int"),
                name=names.chunk,
                init=IRLiteral(text=str(_MAX_CHUNK_WORKGROUPS * spec.kernel.workgroup_size)),
            ),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[
                        GpuLowerer._dispatch_loop(spec),
                        IRIf(
                            condition=IRVar(name=names.ok),
                            then_block=IRBlock(
                                stmts=[
                                    GpuLowerer.read_status(spec),
                                    IRIf(
                                        condition=IRBinOp(
                                            left=IRVar(name=names.ok), op="&&", right=GpuLowerer.status_is_clear(spec)
                                        ),
                                        then_block=IRBlock(stmts=GpuLowerer._readback(spec)),
                                    ),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
            *GpuLowerer._cleanup(spec),
            GpuLowerer.checked_failure_policy(spec),
            GpuLowerer.post_dispatch_failure_policy(spec),
            GpuLowerer.pre_dispatch_failure_policy(spec),
        ]
        return statements

    @staticmethod
    def _dispatch_loop(spec: GpuDispatchSpec) -> IRFor:
        names = spec.names
        offset = IRVar(name=names.offset)
        work_items = IRVar(name=names.work_items)
        chunk = IRVar(name=names.chunk)
        workgroup_size = spec.kernel.workgroup_size
        loop_body = IRBlock(
            stmts=[
                IRAssign(target=IRFieldAccess(obj=IRVar(name=names.uniforms), field="__gpu_off"), value=offset),
                GpuLowerer._call_stmt(
                    "btrc_gpu_write_buffer",
                    IRVar(name=names.gpu),
                    IRVar(name=names.uniform_buffer),
                    IRAddressOf(expr=IRVar(name=names.uniforms)),
                    IRSizeof(operand=IRVar(name=names.uniforms)),
                ),
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=names.work_items,
                    init=IRBinOp(left=IRVar(name=names.length), op="-", right=offset),
                ),
                IRIf(
                    condition=IRBinOp(left=work_items, op=">", right=chunk),
                    then_block=IRBlock(stmts=[IRAssign(target=work_items, value=chunk)]),
                ),
                IRVarDecl(
                    c_type=CType(text="int"),
                    name=names.workgroups,
                    init=IRBinOp(
                        left=IRBinOp(left=work_items, op="+", right=IRLiteral(text=str(workgroup_size - 1))),
                        op="/",
                        right=IRLiteral(text=str(workgroup_size)),
                    ),
                ),
                IRIf(
                    condition=IRCall(
                        callee="btrc_gpu_dispatch",
                        args=[
                            IRVar(name=names.gpu),
                            IRVar(name=names.pipeline),
                            IRVar(name=names.bind_group),
                            IRVar(name=names.workgroups),
                        ],
                    ),
                    then_block=IRBlock(
                        stmts=[IRAssign(target=IRVar(name=names.dispatch_started), value=IRLiteral(text="true"))]
                    ),
                    else_block=IRBlock(stmts=[IRAssign(target=IRVar(name=names.ok), value=IRLiteral(text="false"))]),
                ),
            ]
        )
        return IRFor(
            init=IRVarDecl(c_type=CType(text="int"), name=names.offset, init=IRLiteral(text="0")),
            condition=IRBinOp(
                left=IRVar(name=names.ok), op="&&", right=IRBinOp(left=offset, op="<", right=IRVar(name=names.length))
            ),
            update=IRBinOp(left=offset, op="+=", right=chunk),
            body=loop_body,
        )

    @staticmethod
    def _readback(spec: GpuDispatchSpec) -> list:
        names = spec.names
        if spec.has_output:
            element_type = spec.result_elem_type
            return [
                GpuLowerer.checked_readback(
                    spec,
                    IRVar(name=names.gpu),
                    IRVar(name=names.output_buffer),
                    IRVar(name=OUTPUT_PARAM),
                    GpuLowerer._buffer_size(IRVar(name=names.length), element_type),
                )
            ]
        statements = []
        c_names = dict(spec.parameter_c_names)
        for parameter in spec.declaration.params:
            if not (parameter.type and parameter.type.is_array):
                continue
            buffer = dict(spec.buffers_by_name)[parameter.name]
            if buffer.access != "read_write":
                continue
            statements.append(
                GpuLowerer.checked_readback(
                    spec,
                    IRVar(name=names.gpu),
                    IRVar(name=names.buffer(buffer.name)),
                    IRVar(name=c_names[parameter.name]),
                    GpuLowerer._buffer_size(
                        IRVar(name=GpuLowerer.buffer_length_name(parameter.name)),
                        GpuLowerer.host_scalar_type(buffer.elem_type),
                    ),
                )
            )
        return statements

    @staticmethod
    def _cleanup(spec: GpuDispatchSpec) -> list:
        names = spec.names
        statements = [
            GpuLowerer._call_stmt("btrc_gpu_buffer_destroy", IRVar(name=names.buffer(buffer.name)))
            for buffer in spec.kernel.param_buffers
        ]
        if spec.has_output:
            statements.append(GpuLowerer._call_stmt("btrc_gpu_buffer_destroy", IRVar(name=names.output_buffer)))
        statements.extend(
            [
                GpuLowerer._call_stmt("btrc_gpu_buffer_destroy", IRVar(name=names.status_buffer)),
                GpuLowerer._call_stmt("btrc_gpu_buffer_destroy", IRVar(name=names.uniform_buffer)),
                GpuLowerer._call_stmt("btrc_gpu_bind_group_destroy", IRVar(name=names.bind_group)),
                GpuLowerer._call_stmt("btrc_gpu_compute_pipeline_destroy", IRVar(name=names.pipeline)),
                GpuLowerer._call_stmt("btrc_gpu_shader_destroy", IRVar(name=names.shader)),
            ]
        )
        return statements

    @staticmethod
    def _buffer_size(length, element_type):
        return IRBinOp(left=length, op="*", right=IRSizeof(operand=CType(text=element_type)))

    @staticmethod
    def _call_stmt(callee, *args):
        return IRExprStmt(expr=IRCall(callee=callee, args=list(args)))

    @staticmethod
    def uniforms_and_pipeline(spec: GpuDispatchSpec) -> list:
        names = spec.names
        ok = IRVar(name=names.ok)
        gpu = IRVar(name=names.gpu)
        uniforms = IRVar(name=names.uniforms)
        uniform_buffer = IRVar(name=names.uniform_buffer)
        shader = IRVar(name=names.shader)
        pipeline = IRVar(name=names.pipeline)
        statements = [IRVarDecl(c_type=CType(text=f"struct {spec.uniform_struct}"), name=names.uniforms)]
        c_names = dict(spec.parameter_c_names)
        for parameter in spec.declaration.params:
            if parameter.type and parameter.type.is_array:
                continue
            binding_name = c_names[parameter.name]
            statements.append(
                IRAssign(target=GpuLowerer._uniform_field(names, binding_name), value=IRVar(name=binding_name))
            )
        for buffer in spec.kernel.param_buffers:
            length_name = GpuLowerer.buffer_length_name(buffer.name)
            statements.append(
                IRAssign(target=GpuLowerer._uniform_field(names, length_name), value=IRVar(name=length_name))
            )
        statements.extend(
            [
                IRAssign(target=GpuLowerer._uniform_field(names, "__gpu_n"), value=IRVar(name=names.length)),
                IRVarDecl(c_type=CType(text="void*"), name=names.uniform_buffer, init=IRLiteral(text="NULL")),
                IRIf(
                    condition=ok,
                    then_block=IRBlock(
                        stmts=[
                            IRAssign(
                                target=uniform_buffer,
                                value=IRCall(
                                    callee="btrc_gpu_create_buffer",
                                    args=[
                                        gpu,
                                        IRSizeof(operand=uniforms),
                                        IRBinOp(
                                            left=IRVar(name="BTRC_GPU_UNIFORM"),
                                            op="|",
                                            right=IRVar(name="BTRC_GPU_COPY_DST"),
                                        ),
                                    ],
                                ),
                            )
                        ]
                    ),
                ),
                GpuLowerer.mark_failed_if_null(names.uniform_buffer, names.ok),
                IRVarDecl(c_type=CType(text="void*"), name=names.shader, init=IRLiteral(text="NULL")),
                IRIf(
                    condition=ok,
                    then_block=IRBlock(
                        stmts=[
                            IRAssign(
                                target=shader,
                                value=IRCall(
                                    callee="btrc_gpu_create_shader",
                                    args=[
                                        gpu,
                                        IRCast(
                                            target_type=CType(text="char*"), expr=IRVar(name=f"{spec.kernel.name}_wgsl")
                                        ),
                                    ],
                                ),
                            )
                        ]
                    ),
                ),
                GpuLowerer.mark_failed_if_null(names.shader, names.ok),
                IRVarDecl(c_type=CType(text="void*"), name=names.pipeline, init=IRLiteral(text="NULL")),
                IRIf(
                    condition=ok,
                    then_block=IRBlock(
                        stmts=[
                            IRAssign(
                                target=pipeline,
                                value=IRCall(
                                    callee="btrc_gpu_create_compute_pipeline",
                                    args=[gpu, shader, IRLiteral(text='"main"')],
                                ),
                            )
                        ]
                    ),
                ),
                GpuLowerer.mark_failed_if_null(names.pipeline, names.ok),
            ]
        )
        return statements

    @staticmethod
    def bind_group(spec: GpuDispatchSpec) -> list:
        names = spec.names
        bindings = IRVar(name=names.bindings)
        statements = [
            IRVarDecl(
                c_type=CType(text="void*"), name=names.bindings, array_size=IRLiteral(text=str(spec.total_bindings))
            )
        ]
        binding_index = 0
        for buffer in spec.kernel.param_buffers:
            statements.append(
                IRAssign(
                    target=IRIndex(obj=bindings, index=IRLiteral(text=str(binding_index))),
                    value=IRVar(name=names.buffer(buffer.name)),
                )
            )
            binding_index += 1
        if spec.has_output:
            statements.append(
                IRAssign(
                    target=IRIndex(obj=bindings, index=IRLiteral(text=str(binding_index))),
                    value=IRVar(name=names.output_buffer),
                )
            )
            binding_index += 1
        statements.extend(
            [
                IRAssign(
                    target=IRIndex(obj=bindings, index=IRLiteral(text=str(binding_index))),
                    value=IRVar(name=names.uniform_buffer),
                ),
                IRAssign(
                    target=IRIndex(obj=bindings, index=IRLiteral(text=str(binding_index + 1))),
                    value=IRVar(name=names.status_buffer),
                ),
                IRVarDecl(c_type=CType(text="void*"), name=names.bind_group, init=IRLiteral(text="NULL")),
                IRIf(
                    condition=IRVar(name=names.ok),
                    then_block=IRBlock(
                        stmts=[
                            IRAssign(
                                target=IRVar(name=names.bind_group),
                                value=IRCall(
                                    callee="btrc_gpu_create_bind_group",
                                    args=[
                                        IRVar(name=names.gpu),
                                        IRVar(name=names.pipeline),
                                        bindings,
                                        IRLiteral(text=str(spec.total_bindings)),
                                    ],
                                ),
                            )
                        ]
                    ),
                ),
                GpuLowerer.mark_failed_if_null(names.bind_group, names.ok),
            ]
        )
        return statements

    @staticmethod
    def _uniform_field(names, field):
        return IRFieldAccess(obj=IRVar(name=names.uniforms), field=field)

    @staticmethod
    def initial_state(spec: GpuDispatchSpec) -> list:
        names = spec.names
        ok = IRVar(name=names.ok)
        gpu = IRVar(name=names.gpu)
        statements = [
            IRVarDecl(c_type=CType(text="void*"), name=names.gpu, init=IRLiteral(text="NULL")),
            IRVarDecl(c_type=CType(text="int"), name=names.length, init=spec.dispatch_length_value),
            GpuLowerer.status_declaration(spec),
            IRVarDecl(c_type=CType(text="bool"), name=names.dispatch_started, init=IRLiteral(text="false")),
        ]
        if spec.has_output:
            statements.append(GpuLowerer._capacity_guard(names.length))
        statements.extend(
            [
                IRVarDecl(
                    c_type=CType(text="bool"),
                    name=names.ok,
                    init=IRBinOp(left=IRVar(name=names.length), op=">", right=IRLiteral(text="0")),
                ),
                IRIf(
                    condition=ok,
                    then_block=IRBlock(stmts=[IRAssign(target=gpu, value=IRCall(callee="btrc_gpu_acquire_compute"))]),
                ),
                GpuLowerer.mark_failed_if_null(names.gpu, names.ok),
            ]
        )
        return statements

    @staticmethod
    def _capacity_guard(length_name: str) -> IRIf:
        invalid_target = IRBinOp(
            left=IRUnaryOp(op="!", operand=IRVar(name=OUTPUT_PARAM)),
            op="||",
            right=IRBinOp(left=IRVar(name=OUTPUT_CAPACITY), op="<", right=IRVar(name=length_name)),
        )
        return IRIf(
            condition=IRBinOp(
                left=IRBinOp(left=IRVar(name=length_name), op=">", right=IRLiteral(text="0")),
                op="&&",
                right=invalid_target,
            ),
            then_block=IRBlock(
                stmts=[
                    GpuLowerer.call_stmt(
                        "fputs",
                        IRLiteral(text='"[btrc-gpu] output capacity is smaller than dispatch length\\n"'),
                        IRVar(name="stderr"),
                    ),
                    GpuLowerer.call_stmt("abort"),
                ]
            ),
        )

    @staticmethod
    def storage_buffers(spec: GpuDispatchSpec) -> list:
        names = spec.names
        statements = []
        c_names = dict(spec.parameter_c_names)
        for parameter in spec.declaration.params:
            if not (parameter.type and parameter.type.is_array):
                continue
            buffer = dict(spec.buffers_by_name)[parameter.name]
            statements.extend(
                GpuLowerer._create_storage_buffer(
                    spec,
                    names.buffer(buffer.name),
                    IRVar(name=c_names[parameter.name]),
                    IRVar(name=GpuLowerer.buffer_length_name(parameter.name)),
                    GpuLowerer.host_scalar_type(buffer.elem_type),
                    read_write=buffer.access == "read_write",
                )
            )
        if spec.has_output:
            statements.extend(
                GpuLowerer._create_output_buffer(spec, GpuLowerer.host_scalar_type(spec.kernel.output_buffer.elem_type))
            )
        statements.extend(GpuLowerer.create_status_buffer(spec))
        return statements

    @staticmethod
    def _create_storage_buffer(spec, handle_name, source, length, element_type, *, read_write):
        names = spec.names
        handle = IRVar(name=handle_name)
        size = GpuLowerer.buffer_size(length, element_type)
        usage = IRBinOp(left=IRVar(name="BTRC_GPU_STORAGE"), op="|", right=IRVar(name="BTRC_GPU_COPY_DST"))
        if read_write:
            usage = IRBinOp(left=usage, op="|", right=IRVar(name="BTRC_GPU_COPY_SRC"))
        return [
            IRVarDecl(c_type=CType(text="void*"), name=handle_name, init=IRLiteral(text="NULL")),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=handle,
                            value=IRCall(callee="btrc_gpu_create_buffer", args=[IRVar(name=names.gpu), size, usage]),
                        )
                    ]
                ),
            ),
            GpuLowerer.mark_failed_if_null(handle_name, names.ok),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[GpuLowerer.call_stmt("btrc_gpu_write_buffer", IRVar(name=names.gpu), handle, source, size)]
                ),
            ),
        ]

    @staticmethod
    def _create_output_buffer(spec, element_type):
        names = spec.names
        usage = IRBinOp(
            left=IRBinOp(left=IRVar(name="BTRC_GPU_STORAGE"), op="|", right=IRVar(name="BTRC_GPU_COPY_DST")),
            op="|",
            right=IRVar(name="BTRC_GPU_COPY_SRC"),
        )
        return [
            IRVarDecl(c_type=CType(text="void*"), name=names.output_buffer, init=IRLiteral(text="NULL")),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=IRVar(name=names.output_buffer),
                            value=IRCall(
                                callee="btrc_gpu_create_buffer",
                                args=[
                                    IRVar(name=names.gpu),
                                    GpuLowerer.buffer_size(IRVar(name=names.length), element_type),
                                    usage,
                                ],
                            ),
                        )
                    ]
                ),
            ),
            GpuLowerer.mark_failed_if_null(names.output_buffer, names.ok),
        ]

    @staticmethod
    def buffer_size(length, element_type):
        return IRBinOp(left=length, op="*", right=IRSizeof(operand=CType(text=element_type)))

    @staticmethod
    def mark_failed_if_null(handle_name, ok_name):
        return IRIf(
            condition=IRUnaryOp(op="!", operand=IRVar(name=handle_name)),
            then_block=IRBlock(stmts=[IRAssign(target=IRVar(name=ok_name), value=IRLiteral(text="false"))]),
        )

    @staticmethod
    def call_stmt(callee, *args):
        return IRExprStmt(expr=IRCall(callee=callee, args=list(args)))

    @staticmethod
    def status_declaration(spec: GpuDispatchSpec) -> IRVarDecl:
        return IRVarDecl(c_type=CType(text="uint32_t"), name=spec.names.status_code, init=IRLiteral(text="0U"))

    @staticmethod
    def create_status_buffer(spec: GpuDispatchSpec) -> list:
        names = spec.names
        status_buffer = IRVar(name=names.status_buffer)
        usage = IRBinOp(
            left=IRBinOp(left=IRVar(name="BTRC_GPU_STORAGE"), op="|", right=IRVar(name="BTRC_GPU_COPY_DST")),
            op="|",
            right=IRVar(name="BTRC_GPU_COPY_SRC"),
        )
        return [
            IRVarDecl(c_type=CType(text="void*"), name=names.status_buffer, init=IRLiteral(text="NULL")),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[
                        IRAssign(
                            target=status_buffer,
                            value=IRCall(
                                callee="btrc_gpu_create_buffer",
                                args=[IRVar(name=names.gpu), IRSizeof(operand=IRVar(name=names.status_code)), usage],
                            ),
                        )
                    ]
                ),
            ),
            IRIf(
                condition=IRUnaryOp(op="!", operand=status_buffer),
                then_block=IRBlock(stmts=[IRAssign(target=IRVar(name=names.ok), value=IRLiteral(text="false"))]),
            ),
            IRIf(
                condition=IRVar(name=names.ok),
                then_block=IRBlock(
                    stmts=[
                        GpuLowerer._call_stmt(
                            "btrc_gpu_write_buffer",
                            IRVar(name=names.gpu),
                            status_buffer,
                            IRAddressOf(expr=IRVar(name=names.status_code)),
                            IRSizeof(operand=IRVar(name=names.status_code)),
                        )
                    ]
                ),
            ),
        ]

    @staticmethod
    def read_status(spec: GpuDispatchSpec) -> IRIf:
        names = spec.names
        return GpuLowerer.checked_readback(
            spec,
            IRVar(name=names.gpu),
            IRVar(name=names.status_buffer),
            IRAddressOf(expr=IRVar(name=names.status_code)),
            IRSizeof(operand=IRVar(name=names.status_code)),
        )

    @staticmethod
    def checked_readback(spec: GpuDispatchSpec, gpu, buffer, destination, size) -> IRIf:
        return IRIf(
            condition=IRUnaryOp(
                op="!", operand=IRCall(callee="btrc_gpu_read_buffer_checked", args=[gpu, buffer, destination, size])
            ),
            then_block=IRBlock(stmts=[IRAssign(target=IRVar(name=spec.names.ok), value=IRLiteral(text="false"))]),
        )

    @staticmethod
    def status_is_clear(spec: GpuDispatchSpec) -> IRBinOp:
        return IRBinOp(left=IRVar(name=spec.names.status_code), op="==", right=IRLiteral(text="0U"))

    @staticmethod
    def checked_failure_policy(spec: GpuDispatchSpec) -> IRIf:
        status = IRVar(name=spec.names.status_code)
        diagnostics = []
        for code, message in GPU_STATUS_MESSAGES.items():
            diagnostics.append(
                IRIf(
                    condition=IRBinOp(left=status, op="==", right=IRLiteral(text=f"{code}U")),
                    then_block=IRBlock(
                        stmts=[
                            GpuLowerer._call_stmt(
                                "fputs", IRLiteral(text=GpuLowerer._c_string(message)), IRVar(name="stderr")
                            )
                        ]
                    ),
                )
            )
        diagnostics.append(
            IRIf(
                condition=GpuLowerer._unknown_status(status),
                then_block=IRBlock(
                    stmts=[
                        GpuLowerer._call_stmt(
                            "fputs",
                            IRLiteral(text=GpuLowerer._c_string(GPU_UNKNOWN_STATUS_MESSAGE)),
                            IRVar(name="stderr"),
                        )
                    ]
                ),
            )
        )
        return IRIf(
            condition=IRBinOp(left=status, op="!=", right=IRLiteral(text="0U")),
            then_block=IRBlock(stmts=[*diagnostics, GpuLowerer._call_stmt("exit", IRLiteral(text="1"))]),
        )

    @staticmethod
    def post_dispatch_failure_policy(spec: GpuDispatchSpec) -> IRIf:
        names = spec.names
        return IRIf(
            condition=IRBinOp(
                left=IRUnaryOp(op="!", operand=IRVar(name=names.ok)), op="&&", right=IRVar(name=names.dispatch_started)
            ),
            then_block=IRBlock(
                stmts=[
                    GpuLowerer._call_stmt(
                        "fputs",
                        IRLiteral(text=GpuLowerer._c_string(GPU_TRANSFER_FAILURE_MESSAGE)),
                        IRVar(name="stderr"),
                    ),
                    GpuLowerer._call_stmt("exit", IRLiteral(text="1")),
                ]
            ),
        )

    @staticmethod
    def pre_dispatch_failure_policy(spec: GpuDispatchSpec) -> IRIf:
        names = spec.names
        if spec.cpu_fallback:
            fallback_args = list(spec.cpu_argument_values)
            if spec.has_output:
                fallback_args.extend([IRVar(name=OUTPUT_PARAM), IRVar(name=OUTPUT_CAPACITY)])
            fallback_args.append(IRVar(name=names.length))
            body = [GpuLowerer._call_stmt(spec.cpu_fallback, *fallback_args)]
        else:
            message = f"[btrc-gpu] kernel '{spec.kernel.name}' requires a working GPU; initialization or resource creation failed, or dispatch submission was rejected\n"
            body = [
                GpuLowerer._call_stmt("fputs", IRLiteral(text=GpuLowerer._c_string(message)), IRVar(name="stderr")),
                GpuLowerer._call_stmt("abort"),
            ]
        condition = IRBinOp(
            left=IRUnaryOp(op="!", operand=IRVar(name=names.ok)),
            op="&&",
            right=IRUnaryOp(op="!", operand=IRVar(name=names.dispatch_started)),
        )
        if spec.has_output:
            condition = IRBinOp(
                left=condition, op="&&", right=IRBinOp(left=IRVar(name=names.length), op=">", right=IRLiteral(text="0"))
            )
        return IRIf(condition=condition, then_block=IRBlock(stmts=body))

    @staticmethod
    def _unknown_status(status: IRVar):
        condition = None
        for code in GPU_STATUS_MESSAGES:
            comparison = IRBinOp(left=status, op="!=", right=IRLiteral(text=f"{code}U"))
            condition = comparison if condition is None else IRBinOp(left=condition, op="&&", right=comparison)
        return condition

    @staticmethod
    def _c_string(message: str) -> str:
        escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'

    @staticmethod
    def declaration_capacity(target: IRExpr) -> IRExpr:
        """Capacity of a C array after its declaration has fixed its extent."""
        return GpuLowerer.bare_array_length(target)

    @staticmethod
    def safe_array_size(logical_length: IRExpr) -> IRExpr:
        """Allocate one element for an empty logical result; C11 forbids zero VLAs."""
        return IRTernary(
            condition=IRBinOp(left=logical_length, op=">", right=IRLiteral(text="0")),
            true_expr=logical_length,
            false_expr=IRLiteral(text="1"),
        )

    def assignment_target(
        self,
        ast_target,
        ir_target: IRExpr,
        target_capacity: IRExpr | None,
        provenance: CallableProvenance,
        *,
        result_owned: bool,
    ) -> GpuOutputTarget:
        """Resolve writable data and a proven capacity for a direct assignment."""
        target_type = self._session.type_of(ast_target)
        if GpuLowerer.is_heap_collection(target_type):
            return self.collection_assignment_target(
                ast_target,
                target_type,
                ir_target,
                owned=bool(
                    id(ast_target) not in self._session.owning_overrides
                    and self._ownership.owns_result(ast_target, provenance=provenance)
                ),
                result_owned=result_owned,
            )
        if target_type is None or target_type.pointer_depth > 0:
            raise GpuLowerer._unknown_capacity(ast_target)
        if not target_type.is_array:
            raise CodegenError("array-returning @gpu assignment requires an array or collection target")
        if isinstance(ast_target, Identifier):
            local_status = self._local_c_array_status(ast_target.name)
            if local_status is False:
                raise GpuLowerer._unknown_capacity(ast_target)
            if local_status is None and (not self.backed_global_array(ast_target.name)):
                raise GpuLowerer._unknown_capacity(ast_target)
        elif target_type.array_size is None and (not self.backed_static_field(ast_target)):
            raise GpuLowerer._unknown_capacity(ast_target)
        if not isinstance(ast_target, Identifier):
            capacity = target_capacity if target_capacity is not None else GpuLowerer.bare_array_length(ir_target)
            return self.array_projection_assignment_target(
                ir_target,
                target_type,
                capacity=capacity,
            )
        return GpuOutputTarget(
            declarations=[],
            assignments=[],
            cleanup=[],
            data=ir_target,
            capacity=GpuLowerer.bare_array_length(ir_target),
            result=ir_target,
        )

    def array_projection_assignment_target(
        self,
        ir_target: IRExpr,
        target_type: TypeExpr,
        *,
        capacity: IRExpr,
    ) -> GpuOutputTarget:
        """Snapshot a nontrivial fixed-array LHS before RHS evaluation."""
        data_name = self._session.fresh_temp("__gpu_output_data")
        length_name = self._session.fresh_temp("__gpu_output_len")
        data_declaration = IRVarDecl(c_type=CType(text=self._types.render(target_type)), name=data_name)
        length_declaration = IRVarDecl(c_type=CType(text="int"), name=length_name)
        self._session.record_declaration(data_declaration)
        self._session.record_declaration(length_declaration)
        data = IRVar(name=data_name)
        length = IRVar(name=length_name)
        return GpuOutputTarget(
            declarations=[data_declaration, length_declaration],
            assignments=[IRBinOp(left=data, op="=", right=ir_target), IRBinOp(left=length, op="=", right=capacity)],
            cleanup=[],
            data=data,
            capacity=length,
            result=data,
        )

    def collection_assignment_target(
        self,
        ast_target,
        target_type,
        ir_target,
        *,
        owned,
        result_owned,
    ) -> GpuOutputTarget:
        """Pin the collection denoted by the LHS before lowering RHS effects."""
        temp_name = self._session.fresh_temp("__gpu_output_target")
        declaration = IRVarDecl(c_type=CType(text=self._types.render(target_type)), name=temp_name)
        self._session.record_declaration(declaration)
        stable = IRVar(name=temp_name)
        declarations = [declaration]
        assignments = [IRBinOp(left=stable, op="=", right=ir_target)]
        if not owned:
            assignments.append(self._lifetime.retain_value(stable, target_type))
        self._lifetime.protect_temporary(
            declaration,
            target_type,
            declarations,
            assignments,
            "__btrc_gpu_output_cleanup",
            active=self._cleanup_scope.exception_cleanup_active(),
        )
        result_name = self._session.fresh_temp("__gpu_output_result")
        result_declaration = IRVarDecl(c_type=CType(text=self._types.render(target_type)), name=result_name)
        declarations.append(result_declaration)
        self._session.record_declaration(result_declaration)
        result = IRVar(name=result_name)
        cleanup = [IRBinOp(left=result, op="=", right=stable)]
        if result_owned:
            cleanup.append(IRBinOp(left=stable, op="=", right=IRLiteral(text="NULL")))
        else:
            cleanup.extend(
                self._lifetime.release_and_clear(
                    stable,
                    target_type,
                    declarations,
                    self._types.render(target_type),
                )
            )
        from src.compiler.python.analyzer.types import TypeSystem

        data_name = self._session.fresh_temp("__gpu_output_data")
        length_name = self._session.fresh_temp("__gpu_output_len")
        data_declaration = IRVarDecl(
            c_type=CType(text=self._types.render(TypeSystem.add_outer_pointer(target_type.generic_args[0]))),
            name=data_name,
        )
        length_declaration = IRVarDecl(c_type=CType(text="int"), name=length_name)
        declarations.extend((data_declaration, length_declaration))
        self._session.record_declaration(data_declaration)
        self._session.record_declaration(length_declaration)
        data = IRVar(name=data_name)
        length = IRVar(name=length_name)
        assignments.extend(
            (
                IRBinOp(left=data, op="=", right=IRFieldAccess(obj=stable, field="data", arrow=True)),
                IRBinOp(left=length, op="=", right=IRFieldAccess(obj=stable, field="len", arrow=True)),
            )
        )
        return GpuOutputTarget(
            declarations=declarations,
            assignments=assignments,
            cleanup=cleanup,
            data=data,
            capacity=length,
            result=result,
        )

    def _local_c_array_status(self, name: str) -> bool | None:
        return self._storage.local_c_array_status(name)

    @staticmethod
    def _unknown_capacity(ast_target) -> CodegenError:
        name = ast_target.name if isinstance(ast_target, Identifier) else "expression"
        return CodegenError(f"array-returning @gpu assignment target '{name}' has no provable writable capacity")

    def emit_gpu_functions(self) -> None:
        """Register kernels and fallbacks before generic bodies use them."""
        for declaration in self._analyzed.program.declarations:
            if isinstance(declaration, FunctionDecl) and declaration.is_gpu:
                self.emit_gpu_kernel(declaration)
