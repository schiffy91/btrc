"""Cohesive expressions IR lowering owner."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.types import IndexedProtocolResolver, TypeIdentity
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRDeref,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionRef,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CallExpr,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    FStringExpr,
    FStringLiteral,
    FStringText,
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SizeofExpr,
    SizeofExprOp,
    SizeofType,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
)

from .calls import CallableReturnABI, CallOperand, CallResultPlan, ValuePreparationPlan
from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import (
        CallableProvenance,
        CallableStorageBoundary,
        CallBoundaryLowerer,
        CallLowerer,
        DefaultArgumentLoweringContext,
    )
    from .collections import CollectionLowerer
    from .concurrency import ConcurrencyLowerer
    from .gpu import GpuLowerer
    from .ownership import (
        CleanupScopeState,
        CleanupSlotRegistry,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
        OwnershipOperandOrder,
    )
    from .session import LoweringSession
    from .storage import StorageLowerer
_FLAT_CHAIN_MIN_TERMS = 32


@dataclass(frozen=True)
class LambdaPlan:
    """Deferred lambda declaration consumed by the function owner."""

    node: object
    function_name: str
    capture_abis: tuple[tuple[object, CallableReturnABI], ...]


@dataclass(frozen=True, slots=True)
class FieldAccessMaterialization:
    node: FieldAccessExpr


@dataclass(frozen=True, slots=True)
class IndexMaterialization:
    node: IndexExpr


@dataclass(frozen=True, slots=True)
class AggregateMaterialization:
    plan: object
    elements: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class BinaryMaterialization:
    node: BinaryExpr


@dataclass(frozen=True, slots=True)
class UnaryMaterialization:
    node: UnaryExpr


@dataclass(frozen=True, slots=True)
class OptionalAccessPlan:
    field: str | None = None
    callee: str | None = None


class ExpressionLowerer:
    """Own expressions lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        default_context: DefaultArgumentLoweringContext,
        type_identity: TypeIdentity,
        index_protocols: IndexedProtocolResolver,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cleanup_slots: CleanupSlotRegistry,
        cleanup_scope: CleanupScopeState,
        operand_order: OwnershipOperandOrder,
        call_boundary: CallBoundaryLowerer,
        callable_boundaries: CallableStorageBoundary,
        storage: StorageLowerer,
        calls: CallLowerer,
        collections: CollectionLowerer,
        concurrency: ConcurrencyLowerer,
        gpu: GpuLowerer,
        *,
        program_has_exceptions: bool,
        source_visible_helpers: frozenset[str] | set[str],
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._default_arguments = default_context
        self._type_identity = type_identity
        self._index_protocols = index_protocols
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cleanup_slots = cleanup_slots
        self._cleanup_scope = cleanup_scope
        self._operand_order = operand_order
        self._call_boundary = call_boundary
        self._callable_boundaries = callable_boundaries
        self._storage = storage
        self._calls = calls
        self._collections = collections
        self._concurrency = concurrency
        self._gpu = gpu
        self._program_has_exceptions = bool(program_has_exceptions)
        self._source_visible_helpers = frozenset(source_visible_helpers)

    def lower_expression(self, node, provenance: CallableProvenance):
        return self.lower_expr(
            node,
            provenance,
        )

    def _sequence_operands(
        self,
        nodes,
        provenance: CallableProvenance,
        *,
        materialization,
        result_type,
        promote_result: bool = False,
        result_owned: bool = False,
        keep_nodes=(),
        pin_nodes=(),
        force: bool = False,
        allow_trailing_opaque: bool = False,
        opaque_context: str = "expression",
    ):
        """Materialize an expression's eager operands through one boundary."""
        if self._session.is_unevaluated:
            return None
        keep_ids = {id(node) for node in keep_nodes}
        pin_ids = {id(node) for node in pin_nodes}
        facts = []
        for node in nodes:
            type_expr = self._session.type_of(node)
            owned = bool(
                id(node) not in self._session.owning_overrides
                and self._ownership.owns_result(node, provenance=provenance)
            )
            facts.append(
                (
                    node,
                    type_expr,
                    owned,
                    id(node) in keep_ids,
                    id(node) in pin_ids and not owned and self._ownership.borrowed_value_can_be_pinned(node),
                )
            )
        automatic_pins = self._operand_order.source_order_pin_flags(
            nodes,
            [type_expr for _node, type_expr, *_rest in facts],
            [owned for _node, _type_expr, owned, *_rest in facts],
        )
        facts = [
            (node, type_expr, owned, keep, pin or automatic_pins[index])
            for index, (node, type_expr, owned, keep, pin) in enumerate(facts)
        ]
        lifetime_required = any(owned or keep or pin for _node, _type_expr, owned, keep, pin in facts)
        if not (force or lifetime_required):
            return None
        missing = [index for index, (_node, type_expr, *_rest) in enumerate(facts) if type_expr is None]
        if missing:
            trailing = len(facts) - 1
            if allow_trailing_opaque and missing == [trailing]:
                node, _type_expr, owned, keep, pin = facts.pop()
                if owned or keep or pin:
                    self._ownership.reject_opaque_ordering(node, opaque_context)
            else:
                self._ownership.reject_opaque_ordering(facts[missing[0]][0], opaque_context)
        fact_types = {id(node): type_expr for node, type_expr, *_rest in facts}

        evaluation = self._call_boundary.start()
        for node, type_expr, owned, keep, pin in facts:
            override_types = {key: fact_types[key] for key in evaluation.values if key in fact_types}
            with self._session.operand_scope(evaluation.values, override_types):
                lowered = self.lower_expression(node, provenance)
            self._call_boundary.append(
                evaluation,
                CallOperand(
                    node=node,
                    type_expr=type_expr,
                    c_type=self._operand_order.operand_c_type(node, type_expr),
                    keep=keep,
                    pin=pin,
                    owned=owned,
                    lowered=lowered,
                ),
            )
        with self._session.operand_scope(evaluation.values, fact_types):
            call = self._materialize_sequenced(materialization, provenance)
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(
                c_type=(self._types.render(result_type) if result_type is not None else None),
                type_expr=result_type,
                promote=promote_result,
                owned=bool(result_owned or promote_result),
            ),
        )

    def _materialize_sequenced(self, materialization, provenance: CallableProvenance) -> IRExpr:
        """Materialize one inert expression plan after operand stabilization."""
        if isinstance(materialization, FieldAccessMaterialization):
            return self._lower_field_access_plain(materialization.node, provenance)
        if isinstance(materialization, IndexMaterialization):
            return self._lower_index_plain(materialization.node, provenance)
        if isinstance(materialization, AggregateMaterialization):
            return self._collections.materialize_aggregate(
                materialization.plan,
                [self.lower_expr(element, provenance) for element in materialization.elements],
            )
        if isinstance(materialization, BinaryMaterialization):
            return self._lower_binary_plain(materialization.node, provenance)
        if isinstance(materialization, UnaryMaterialization):
            return self._lower_unary_plain(materialization.node, provenance)
        raise TypeError(f"unsupported sequenced expression plan: {type(materialization).__name__}")

    def lower_call_plan(
        self,
        plan,
        provenance: CallableProvenance,
    ):
        if isinstance(plan.callee, str):
            callee = plan.callee
        elif isinstance(plan.callee, Identifier):
            callee = provenance.source_function_c_name(plan.callee.name, plan.source)
        else:
            callee = self.lower_expr(
                plan.callee,
                provenance,
            )
        operands = [
            self.lower_expr(
                operand,
                provenance,
            )
            for operand in plan.operands
        ]
        return self._calls.materialize(plan, callee, operands)

    def lower_static_initializer(
        self,
        node,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Recursively lower a static initializer through typed plans."""
        plan = self._collections.plan_static(node, provenance)
        if plan is None:
            return self.lower_expr(
                node,
                provenance,
            )
        elements = [
            self.lower_static_initializer(
                element,
                provenance,
            )
            for element in node.elements
        ]
        return self._collections.materialize_static(plan, elements)

    def prepare_value(
        self,
        node,
        target_type,
        provenance: CallableProvenance,
    ):
        """Lower and materialize one target-directed value plan."""
        plan = self._calls.plan_value(node, target_type, provenance)
        requests = self._session.hosted_result_conversion_requests
        key = id(node)
        missing = object()
        previous = requests.get(key, missing)
        if plan.hosted_mode is not None:
            requests[key] = (plan.hosted_mode, plan.target_type)
        try:
            lowered = self.lower_expr(
                node,
                provenance,
            )
        finally:
            if plan.hosted_mode is not None:
                if previous is missing:
                    requests.pop(key, None)
                else:
                    requests[key] = previous
        return self.materialize_prepared_value(
            plan,
            lowered,
        )

    def prepare_lowered_value(
        self,
        node,
        target_type,
        lowered: IRExpr,
        provenance: CallableProvenance,
    ):
        """Materialize a value whose ordinary expression traversal is complete."""
        plan = self._calls.plan_value(node, target_type, provenance)
        return self.materialize_prepared_value(
            plan,
            lowered,
        )

    def materialize_prepared_value(
        self,
        plan: ValuePreparationPlan,
        lowered: IRExpr,
    ):
        """Apply a resolved conversion plan to explicit source IR."""
        if not plan.string_conversion:
            return self._calls.materialize_value(plan, lowered)
        operand = CallOperand(
            node=plan.source,
            type_expr=plan.source_type,
            c_type=self._types.render(plan.source_type),
            owned=plan.source_owned,
            lowered=lowered,
        )
        evaluation = self._call_boundary.evaluate([operand])
        converted_call = self._calls.materialize_string_conversion(plan, evaluation.values[id(plan.source)])
        string_type = TypeExpr(base="string")
        converted = self._call_boundary.materialize(
            evaluation,
            converted_call,
            CallResultPlan(
                c_type=self._types.render(string_type),
                type_expr=string_type,
                owned=True,
            ),
        )
        return self._calls.materialize_value(plan, lowered, converted=converted)

    def constructor_cleanup_guard(self, self_declaration: IRVarDecl):
        """Return registration/discard statements around a throwing init call."""
        if not self.program_uses_exceptions():
            return ([], [])
        self._session.require_helper("__btrc_cleanup_mark")
        self._session.require_helper("__btrc_discard_cleanups_to")
        self._session.require_helper("__btrc_arc_abandon")
        mark = self._session.fresh_temp("__btrc_constructor_cleanup")
        before = [
            IRVarDecl(
                c_type=CType(text="int"),
                name=mark,
                init=IRCall(callee="__btrc_cleanup_mark", args=[], helper_ref="__btrc_cleanup_mark"),
            ),
            IRExprStmt(
                expr=self._cleanup_slots.register(
                    self_declaration, IRFunctionRef(name="__btrc_arc_abandon"), direct=True
                )
            ),
        ]
        after = [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups_to",
                    args=[IRVar(name=mark)],
                    helper_ref="__btrc_discard_cleanups_to",
                )
            )
        ]
        return (before, after)

    def program_uses_exceptions(self) -> bool:
        """Return the module-wide ownership contract for throwing constructors."""
        return self._program_has_exceptions

    @staticmethod
    def unsupported_node(phase: str, node) -> CodegenError:
        return CodegenError(f"unsupported {phase} node: {type(node).__name__}")

    def lower_expr(self, node, provenance: CallableProvenance) -> IRExpr:
        """Lower an AST expression node to an IRExpr."""
        if node is None:
            return IRLiteral(text="0")
        if self is not None:
            override = self._session.owning_overrides.get(id(node))
            if override is not None:
                return override
        if isinstance(node, IntLiteral):
            return IRLiteral(text=self._types.format_c_integer_literal(node.raw, node.value))
        if isinstance(node, FloatLiteral):
            text = node.raw or str(node.value)
            if self._session.gpu_cpu_index and (not text.endswith(("f", "F"))):
                text += "f"
            return IRLiteral(text=text)
        if isinstance(node, StringLiteral):
            return IRLiteral(text=node.value)
        if isinstance(node, CharLiteral):
            return IRLiteral(text=node.value)
        if isinstance(node, BoolLiteral):
            return IRLiteral(text="true" if node.value else "false")
        if isinstance(node, NullLiteral):
            return IRLiteral(text="NULL")
        if isinstance(node, Identifier):
            return self._lower_identifier(
                node,
                provenance,
            )
        if isinstance(node, SelfExpr):
            return IRVar(name="self")
        if isinstance(node, SuperExpr):
            parent_type = self._analyzed.node_types.get(id(node))
            if parent_type is None:
                raise CodegenError("unresolved super expression")
            return IRCast(target_type=CType(text=self._types.render(parent_type)), expr=IRVar(name="self"))
        if isinstance(node, BinaryExpr):
            return self._lower_binary(
                node,
                provenance,
            )
        if isinstance(node, UnaryExpr):
            return self._lower_unary(
                node,
                provenance,
            )
        if isinstance(node, CallExpr):
            if isinstance(node.callee, Identifier) and self._gpu.is_gpu_cpu_builtin(node.callee.name):
                return self._gpu.lower_gpu_cpu_builtin(
                    node.callee.name,
                    node.args,
                    [
                        self.lower_expr(
                            argument,
                            provenance,
                        )
                        for argument in node.args
                    ],
                )
            if self._gpu.is_direct_gpu_call(node, provenance):
                return self._gpu.materialize_direct_gpu_call(
                    node,
                    [
                        self.lower_expr(
                            argument,
                            provenance,
                        )
                        for argument in node.args
                    ],
                    provenance,
                )
            if isinstance(node.callee, FieldAccessExpr):
                receiver_type = self._session.type_of(node.callee.obj)
                synchronized = self._concurrency.lower_sync_method(
                    node.callee.obj,
                    self.lower_expr(
                        node.callee.obj,
                        provenance,
                    ),
                    node.callee.field,
                    receiver_type,
                    [
                        self.lower_expr(
                            argument,
                            provenance,
                        )
                        for argument in node.args
                    ],
                )
                if synchronized is not None:
                    return synchronized
            if isinstance(node.callee, FieldAccessExpr) and node.callee.optional:
                return self.lower_optional_method_call(
                    node,
                    provenance,
                )
            return self.lower_call_plan(
                self._calls.plan(node),
                provenance,
            )
        if isinstance(node, FieldAccessExpr):
            return self._lower_field_access(
                node,
                provenance,
            )
        if isinstance(node, IndexExpr):
            return self._lower_index(
                node,
                provenance,
            )
        if isinstance(node, AssignExpr):
            if isinstance(node.value, CallExpr) and self._gpu.output_gpu_call_name(node.value, provenance) is not None:
                target_type = self._session.type_of(node.target)
                target = self.lower_expr(
                    node.target,
                    provenance,
                )
                target_capacity = (
                    self.lower_expr(
                        target_type.array_size,
                        provenance,
                    )
                    if target_type is not None and target_type.array_size is not None
                    else None
                )
                result = self._gpu.lower_gpu_output_assignment(
                    node.value,
                    node.target,
                    target,
                    target_capacity,
                    [
                        self.lower_expr(
                            argument,
                            provenance,
                        )
                        for argument in node.value.args
                    ],
                    provenance,
                )
                provenance.rebind_assignment(node)
                return result
            plan = self._storage.plan_store(
                node.target,
                node.value,
                operator=node.op,
            )
            result = self._storage.materialize_store(
                plan,
                self.lower_expr(
                    node.target,
                    provenance,
                ),
                self.lower_expr(
                    node.value,
                    provenance,
                ),
            )
            provenance.rebind_assignment(node)
            return result
        if isinstance(node, CastExpr):
            self._callable_boundaries.reject_nonportable_callable_cast(node, provenance)
            target_type = self._types.render(node.target_type)
            reference_types = set(self._analyzed.class_table)
            reference_types.update(self._analyzed.interface_table)
            if node.target_type.base in reference_types and (not target_type.endswith("*")):
                target_type += "*"
            return IRCast(
                target_type=CType(text=target_type),
                expr=self.lower_expr(
                    node.expr,
                    provenance,
                ),
            )
        if isinstance(node, SizeofExpr):
            return self._lower_sizeof(
                node,
                provenance,
            )
        if isinstance(node, TernaryExpr):
            owns_result = self._ownership.owns_result(node, provenance=provenance)
            condition = self.lower_expr(
                node.condition,
                provenance,
            )
            with provenance.isolated_flow() as true_isolation:
                true_expr = self.lower_expr(
                    node.true_expr,
                    provenance,
                )
            with provenance.isolated_flow() as false_isolation:
                false_expr = self.lower_expr(
                    node.false_expr,
                    provenance,
                )
            assert true_isolation.outgoing is not None
            assert false_isolation.outgoing is not None
            provenance.join_flows(true_isolation.outgoing, false_isolation.outgoing)
            if owns_result:
                true_expr = self._ownership.normalize_branch(node.true_expr, true_expr, provenance)
                false_expr = self._ownership.normalize_branch(node.false_expr, false_expr, provenance)
            return self._types.lower_typed_ternary(
                condition,
                true_expr,
                false_expr,
                self._analyzed.node_types.get(id(node.true_expr)),
                self._analyzed.node_types.get(id(node.false_expr)),
            )
        if isinstance(node, NewExpr):
            instance_type = self._default_arguments.resolve_type(node.type)
            operands = [
                self.lower_expr(
                    argument,
                    provenance,
                )
                for argument in node.args
            ]
            if instance_type.base == "Mutex":
                if not operands:
                    raise CodegenError("Mutex construction requires one value")
                value_type = (
                    instance_type.generic_args[0] if instance_type.generic_args else self._session.type_of(node.args[0])
                )
                return self._concurrency.create_mutex_value(
                    operands[0],
                    value_type,
                )
            return self._calls.materialize(
                self._calls.plan_new(node, instance_type),
                self._calls.constructor_symbol(instance_type),
                operands,
            )
        if isinstance(node, ListLiteral):
            return self._collections.lower_list_literal(
                node,
                [
                    self.lower_expr(
                        element,
                        provenance,
                    )
                    for element in node.elements
                ],
            )
        if isinstance(node, MapLiteral):
            return self._collections.lower_map_literal(
                node,
                [
                    (
                        self.lower_expr(
                            entry.key,
                            provenance,
                        ),
                        self.lower_expr(
                            entry.value,
                            provenance,
                        ),
                    )
                    for entry in node.entries
                ],
            )
        if isinstance(node, FStringLiteral):
            return self.lower_fstring(
                node,
                provenance,
            )
        if isinstance(node, LambdaExpr):
            lambda_id = self._session.fresh_lambda_id()
            function_name = f"__btrc_lambda_{lambda_id}"
            capture_abis = tuple((capture, provenance.return_abi_for_name(capture.name)) for capture in node.captures)
            self._session.pending_lambdas.append(LambdaPlan(node, function_name, capture_abis))
            return IRFunctionRef(name=function_name)
        if isinstance(node, TupleLiteral):
            return self._lower_aggregate(
                self._collections.plan_tuple(node, provenance),
                node.elements,
                provenance,
            )
        if isinstance(node, SpawnExpr):
            lowered_function = (
                None
                if isinstance(node.fn, LambdaExpr)
                else self.lower_expr(
                    node.fn,
                    provenance,
                )
            )
            return self._concurrency.lower_spawn(
                node,
                lowered_function=lowered_function,
                provenance=provenance,
            )
        if isinstance(node, BraceInitializer):
            return self._lower_aggregate(
                self._collections.plan_brace(node, provenance),
                node.elements,
                provenance,
            )
        raise ExpressionLowerer.unsupported_node("expression", node)

    def _lower_identifier(self, node: Identifier, provenance: CallableProvenance) -> IRExpr:
        """Lower an identifier, handling enum values."""
        name = node.name
        predefined = self._default_arguments.predefined_identifier(node)
        if predefined is not None:
            return IRLiteral(text=predefined)
        if self._session.local_is_declared(name):
            return self._source_identifier_var(node, self._ownership.source_binding_c_name(name, provenance))
        if name in self._source_visible_helpers and (not self._session.local_is_declared(name)):
            self._session.require_helper(name)
            return IRFunctionRef(name=name)
        enum_members = self._session.enum_lowering_members
        if name in enum_members:
            owner = self._session.enum_lowering_owner
            prefix = f"{owner}_" if owner else ""
            return IRVar(name=f"{prefix}{name}")
        for enum_name, values in self._analyzed.enum_table.items():
            if name in values:
                prefix = f"{enum_name}_" if enum_name else ""
                return IRVar(name=f"{prefix}{name}")
        if name in self._analyzed.function_table and (not self._session.local_is_declared(name)):
            return IRFunctionRef(name=provenance.source_function_c_name(name))
        return self._source_identifier_var(node, name)

    def _source_identifier_var(self, node, c_name):
        return IRVar(name=c_name).record_array_value(self._analyzed.node_types.get(id(node)))

    def _lower_sizeof(self, node: SizeofExpr, provenance: CallableProvenance) -> IRExpr:
        if isinstance(node.operand, SizeofType):
            return IRSizeof(operand=CType(text=self._types.render(node.operand.type)))
        elif isinstance(node.operand, SizeofExprOp):
            expression = node.operand.expr
            expression_type = self._analyzed.node_types.get(id(expression))
            if (
                expression_type is not None
                and (not expression_type.is_array)
                and (not isinstance(expression, StringLiteral))
            ):
                return IRSizeof(operand=CType(text=self._types.render(expression_type)))
            self._session.unevaluated_depth += 1
            try:
                return IRSizeof(
                    operand=self.lower_expr(
                        expression,
                        provenance,
                    )
                )
            finally:
                self._session.unevaluated_depth -= 1
        return IRSizeof(operand=CType(text="void"))

    def _lower_field_access(self, node: FieldAccessExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower field access, handling optional chaining and special types."""
        result_type = self._analyzed.node_types.get(id(node))
        from src.compiler.python.analyzer.storage import StorageModel

        custom_getter = StorageModel.custom_property_getter(
            self._analyzed.class_table, self._analyzed.node_types.get(id(node.obj)), node.field
        )
        dependencies = self._ownership.borrowed_projection_owner_operands(node.obj, provenance)
        sequenced = self._sequence_operands(
            [*dependencies, node.obj],
            provenance,
            materialization=FieldAccessMaterialization(node),
            result_type=result_type,
            pin_nodes=[node.obj] if custom_getter else [],
            promote_result=bool(
                self._values.is_managed(result_type) and (not self._ownership.projection_is_owned_call(node))
            ),
        )
        if sequenced is not None:
            return sequenced
        return self._lower_field_access_plain(
            node,
            provenance,
        )

    def _lower_field_access_plain(self, node: FieldAccessExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower one field access after any owning receiver is stabilized."""
        obj = self.lower_expr(
            node.obj,
            provenance,
        )
        obj_type = self._analyzed.node_types.get(id(node.obj))
        field_name = provenance.source_field_c_name(node.obj, node.field)
        from src.compiler.python.syntax.ast.generated import SelfExpr

        if isinstance(node.obj, SelfExpr) and self._session.current_property_backing == node.field:
            return IRFieldAccess(obj=obj, field=f"_prop_{node.field}", arrow=True)
        if (
            obj_type
            and self._types.is_direct_generic_instance_reference(obj_type)
            and (node.field in ("len", "length", "size"))
        ):
            if node.optional:
                return self._lower_optional_access(
                    obj,
                    obj_type,
                    self._analyzed.node_types.get(id(node)),
                    OptionalAccessPlan(field="len"),
                )
            return IRFieldAccess(obj=obj, field="len", arrow=True)
        if (
            isinstance(node.obj, Identifier)
            and node.obj.name in self._analyzed.enum_table
            and (not self._session.local_is_declared(node.obj.name))
            and (node.field in self._analyzed.enum_table[node.obj.name])
        ):
            return IRVar(name=f"{node.obj.name}_{node.field}")
        if (
            isinstance(node.obj, Identifier)
            and node.obj.name in self._analyzed.rich_enum_table
            and (not self._session.local_is_declared(node.obj.name))
        ):
            return IRVar(name=f"{node.obj.name}_{node.field}_TAG")
        if (
            isinstance(node.obj, Identifier)
            and node.obj.name in self._analyzed.class_table
            and (not self._session.local_is_declared(node.obj.name))
        ):
            class_info = self._analyzed.class_table[node.obj.name]
            method = class_info.methods.get(node.field)
            symbol = f"{node.obj.name}_{node.field}"
            if method is not None and method.access == "class":
                return IRFunctionRef(name=symbol)
            return IRVar(name=symbol)
        if obj_type and obj_type.base in self._analyzed.class_table:
            cls_info = self._analyzed.class_table[obj_type.base]
            if obj_type.generic_args and cls_info.generic_params:
                callee_prefix = self._type_identity.specialization_symbol(obj_type.base, obj_type.generic_args)
            else:
                callee_prefix = obj_type.base
            if node.field in cls_info.properties:
                if node.optional:
                    return self._lower_optional_access(
                        obj,
                        obj_type,
                        self._analyzed.node_types.get(id(node)),
                        OptionalAccessPlan(callee=f"{callee_prefix}_get_{node.field}"),
                    )
                return IRCall(callee=f"{callee_prefix}_get_{node.field}", args=[obj])
        if node.optional:
            return self._lower_optional_access(
                obj,
                obj_type,
                self._analyzed.node_types.get(id(node)),
                OptionalAccessPlan(field=field_name),
            )
        field = IRFieldAccess(obj=obj, field=field_name, arrow=self.receiver_uses_arrow(obj_type, explicit=node.arrow))
        return field.record_array_projection(self._analyzed.node_types.get(id(node)))

    def receiver_uses_arrow(self, receiver_type, *, explicit: bool = False) -> bool:
        """Choose C member syntax from the receiver's concrete storage shape."""
        if explicit:
            return True
        resolved = self._types.canonical_type(receiver_type)
        return bool(resolved and (resolved.pointer_depth > 0 or resolved.base in self._analyzed.class_table))

    def _lower_optional_access(
        self,
        receiver,
        receiver_type,
        result_type,
        plan: OptionalAccessPlan,
    ) -> IRExpr:
        """Evaluate one nullable receiver once, then conditionally read its value."""
        name = self._session.fresh_temp("__btrc_optional")
        temporary = IRVar(name=name)
        c_type = self._types.render(receiver_type) if receiver_type is not None else "void*"
        if plan.callee is not None:
            access = IRCall(callee=plan.callee, args=[temporary])
        elif plan.field is not None:
            access = IRFieldAccess(obj=temporary, field=plan.field, arrow=True)
        else:
            raise ValueError("optional access plan requires a field or callee")
        return IRStmtExpr(
            stmts=[IRVarDecl(c_type=CType(text=c_type), name=name)],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=temporary, op="=", right=receiver),
                    IRTernary(
                        condition=IRBinOp(left=temporary, op="!=", right=IRLiteral(text="NULL")),
                        true_expr=access,
                        false_expr=self._optional_zero(
                            result_type,
                        ),
                    ),
                ]
            ),
        )

    def _optional_zero(self, result_type):
        return self._types.optional_zero_value(result_type)

    def _lower_index(self, node: IndexExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower index expression: list[i] → List_get(list, i), map[k] → Map_get(map, k)."""
        result_type = self._analyzed.node_types.get(id(node))
        projection_call = self._ownership.projection_is_owned_call(node)
        receiver_type = self._analyzed.node_types.get(id(node.obj))
        protocol_getter = self._index_protocols.class_info(receiver_type, method="get")
        dependencies = self._ownership.borrowed_projection_owner_operands(node.obj, provenance)
        sequenced = self._sequence_operands(
            [*dependencies, node.obj, node.index],
            provenance,
            materialization=IndexMaterialization(node),
            result_type=result_type,
            pin_nodes=[node.obj] if protocol_getter is not None else [],
            promote_result=bool(self._values.is_managed(result_type) and (not projection_call)),
            result_owned=bool(self._values.is_managed(result_type) and projection_call),
            force=self._operand_order.operands_require_order([*dependencies, node.obj, node.index]),
        )
        if sequenced is not None:
            return sequenced
        return self._lower_index_plain(
            node,
            provenance,
        )

    def _lower_aggregate(
        self,
        plan,
        elements,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Lower aggregate leaves, then materialize their resolved shape."""

        materialization = AggregateMaterialization(plan, tuple(elements))
        sequenced = self._sequence_operands(
            list(elements),
            provenance,
            materialization=materialization,
            result_type=self._session.type_of(plan.source),
            force=self._operand_order.operands_require_order(elements),
        )
        return sequenced if sequenced is not None else self._materialize_sequenced(materialization, provenance)

    def _lower_index_plain(self, node: IndexExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower one index projection after its receiver is stabilized."""
        obj = self.lower_expr(
            node.obj,
            provenance,
        )
        index = self.lower_expr(
            node.index,
            provenance,
        )
        obj_type = self._analyzed.node_types.get(id(node.obj))
        gpu_length = self._gpu.cpu_array_length(node.obj.name) if isinstance(node.obj, Identifier) else None
        if gpu_length is not None:
            self._session.require_helper("__btrc_gpu_index_check")
            index = IRCall(
                callee="__btrc_gpu_index_check",
                args=[index, IRVar(name=gpu_length)],
                helper_ref="__btrc_gpu_index_check",
            )
        protocol = self._index_protocols.class_info(obj_type, method="get")
        if protocol is not None:
            prefix = (
                self._type_identity.specialization_symbol(obj_type.base, obj_type.generic_args)
                if obj_type.generic_args and protocol.generic_params
                else obj_type.base
            )
            return IRCall(callee=f"{prefix}_get", args=[obj, index])
        return IRIndex(obj=obj, index=index).record_index_storage(obj_type)

    def lower_fstring(self, node: FStringLiteral, provenance: CallableProvenance):
        """Lower a normal f-string through the shared typed implementation."""
        return self.lower_typed_fstring(
            node,
            provenance,
        )

    def lower_typed_fstring(
        self,
        node,
        provenance: CallableProvenance,
    ):
        """Format interpolations once and consume any caller-owned arguments."""
        format_parts = []
        prepared_items = []
        argument_specs = []
        for part in node.parts:
            if isinstance(part, FStringText):
                format_parts.append(part.text.replace("%", "%%"))
                continue
            if not isinstance(part, FStringExpr):
                continue
            expression = part.expression
            source_type = self._types.canonical_type(self._session.type_of(expression))
            target_type = TypeExpr(base="string") if self._types.has_to_string(source_type) else source_type
            prepared = self.prepare_value(
                expression,
                target_type,
                provenance,
            )
            spec = "%s" if prepared.converted else self._types.format_spec(source_type)
            if source_type is None:
                spec = ExpressionLowerer._untracked_format(expression, spec)
            c_type = (
                self._types.render(prepared.effective_type)
                if prepared.effective_type is not None
                else "char*"
                if spec == "%s"
                else "int"
            )
            prepared_items.append((expression, prepared, c_type))
            argument_specs.append((expression, prepared.effective_type, spec, len(format_parts)))
            format_parts.append(spec)
        format_text = "".join(format_parts)
        if not prepared_items:
            return IRLiteral(text=f'"{format_text}"')
        prepared_pairs = [(expression, prepared) for expression, prepared, _c_type in prepared_items]
        pins = self._calls.prepared_value_pin_flags(prepared_pairs)
        operands = [
            CallOperand(
                node=expression,
                type_expr=prepared.effective_type,
                c_type=c_type,
                pin=pins[index],
                owned=prepared.owned,
                lowered=prepared.value,
            )
            for index, (expression, prepared, c_type) in enumerate(prepared_items)
        ]
        self._session.require_helper("__btrc_string_alloc")
        string_type = TypeExpr(base="string")

        def build(overrides):
            arguments = []
            formats = list(format_parts)
            for expression, value_type, spec, part_index in argument_specs:
                adapted = self._calls.adapt_printf_arg(
                    overrides[id(expression)],
                    value_type,
                    spec,
                )
                formats[part_index] = adapted.format_spec
                arguments.append(adapted.value)
            fmt = IRLiteral(text=f'''"{"".join(formats)}"''')
            length = self._session.fresh_temp("__fstr_len")
            buffer = self._session.fresh_temp("__fstr_buf")
            declarations = [
                IRVarDecl(c_type=CType(text="int"), name=length),
                IRVarDecl(c_type=CType(text="char*"), name=buffer),
            ]
            for declaration in declarations:
                self._session.record_declaration(declaration)
            size = IRBinOp(
                left=IRCast(target_type=CType(text="size_t"), expr=IRVar(name=length)),
                op="+",
                right=IRLiteral(text="1"),
            )
            sequence = [
                IRBinOp(
                    left=IRVar(name=length),
                    op="=",
                    right=IRCall(
                        callee="snprintf", args=[IRLiteral(text="NULL"), IRLiteral(text="0"), fmt, *arguments]
                    ),
                ),
                IRBinOp(
                    left=IRVar(name=buffer),
                    op="=",
                    right=IRCall(
                        callee="__btrc_string_alloc", args=[IRVar(name=length)], helper_ref="__btrc_string_alloc"
                    ),
                ),
                IRCall(callee="snprintf", args=[IRVar(name=buffer), size, fmt, *arguments]),
                IRVar(name=buffer),
            ]
            return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

        evaluation = self._call_boundary.evaluate(operands)
        call = build(evaluation.values)
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(c_type="char*", type_expr=string_type, owned=True),
        )

    @staticmethod
    def _untracked_format(expression, fallback):
        if isinstance(expression, (FStringLiteral, StringLiteral)):
            return "%s"
        if isinstance(expression, CallExpr) and isinstance(expression.callee, FieldAccessExpr):
            if expression.callee.field in {
                "capitalize",
                "join",
                "repeat",
                "replace",
                "reverse",
                "split",
                "str",
                "substring",
                "toLower",
                "toString",
                "toUpper",
                "trim",
            }:
                return "%s"
        return fallback or "%d"

    def operator_rhs_keep(self, left_type, operator: str, right_type) -> bool:
        """Whether an overloaded operator's RHS needs a call-duration keep."""
        if not self._values.is_managed(right_type) or left_type is None:
            return False
        magic = {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__div__",
            "%": "__mod__",
            "==": "__eq__",
            "!=": "__ne__",
            "<": "__lt__",
            ">": "__gt__",
            "<=": "__le__",
            ">=": "__ge__",
        }.get(operator)
        class_info = self._analyzed.class_table.get(left_type.base)
        method = class_info.methods.get(magic) if class_info is not None and magic else None
        return bool(method is not None and method.params and method.params[0].keep)

    def _lower_binary(self, node: BinaryExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower a binary expression, handling special operators."""
        if node.op == "+":
            flattened = self.lower_long_string_concat(
                node,
                provenance,
            )
            if flattened is not None:
                return flattened
        prepared_overload = self._lower_prepared_overload(
            node,
            provenance,
        )
        if prepared_overload is not None:
            return prepared_overload
        if node.op not in {"??", "&&", "||"}:
            left_type = self._analyzed.node_types.get(id(node.left))
            right_type = self._analyzed.node_types.get(id(node.right))
            keep_nodes = [node.right] if self.operator_rhs_keep(left_type, node.op, right_type) else []
            pin_nodes = (
                [node.left]
                if self.overloaded_binary_method(left_type, node.op) is not None and self._values.is_managed(left_type)
                else []
            )
            sequenced = self._sequence_operands(
                [node.left, node.right],
                provenance,
                materialization=BinaryMaterialization(node),
                result_type=self._analyzed.node_types.get(id(node)),
                keep_nodes=keep_nodes,
                pin_nodes=pin_nodes,
                force=self._operand_order.operands_require_order([node.left, node.right]),
                allow_trailing_opaque=True,
                opaque_context=f"operator '{node.op}'",
            )
            if sequenced is not None:
                return sequenced
        return self._lower_binary_plain(
            node,
            provenance,
        )

    def _lower_binary_plain(self, node: BinaryExpr, provenance: CallableProvenance) -> IRExpr:
        """Lower one binary operation after owned operands are stabilized."""
        owns_result = bool(node.op == "??" and self._ownership.owns_result(node, provenance=provenance))
        if node.op in {"??", "&&", "||"}:
            left = self.lower_expr(
                node.left,
                provenance,
            )
            skipped_flow = provenance.snapshot()
            with provenance.isolated_flow() as right_isolation:
                right = self.lower_expr(
                    node.right,
                    provenance,
                )
            assert right_isolation.outgoing is not None
            provenance.join_flows(skipped_flow, right_isolation.outgoing)
        else:
            left = self.lower_expr(
                node.left,
                provenance,
            )
            right = self.lower_expr(
                node.right,
                provenance,
            )
        if owns_result:
            left = self._ownership.normalize_branch(node.left, left, provenance)
            right = self._ownership.normalize_branch(node.right, right, provenance)
        left_type = self._analyzed.node_types.get(id(node.left))
        right_type = self._analyzed.node_types.get(id(node.right))
        op = node.op
        overloaded = self.lower_overloaded_values(
            left_type,
            right_type,
            op,
            left,
            right,
        )
        if overloaded is not None:
            return overloaded
        lowered = self._types.lower_typed_binary(
            op,
            left,
            right,
            left_type,
            right_type,
            allow_unresolved_c_operands=True,
            left_is_optional_value=isinstance(node.left, FieldAccessExpr) and node.left.optional,
        )
        if lowered is not None:
            return lowered
        return IRBinOp(left=left, op=op, right=right)

    def lower_overloaded_values(self, left_type, right_type, op: str, left: IRExpr, right: IRExpr) -> IRExpr | None:
        """Lower one class operation from already-resolved operand types."""
        method = self.overloaded_binary_method(left_type, op)
        if method is None:
            return None
        if method.params:
            right = self._types.upcast_class_pointer(method.params[0].type, right_type, right)
        class_name = (
            self._type_identity.specialization_symbol(left_type.base, left_type.generic_args)
            if left_type.generic_args
            else left_type.base
        )
        return IRCall(callee=f"{class_name}_{ExpressionLowerer._operator_method_name(op)}", args=[left, right])

    def overloaded_binary_method(self, left_type, op: str):
        """Return the source method implementing an overloaded binary operator."""
        magic = ExpressionLowerer._operator_method_name(op)
        if not magic or not left_type:
            return None
        cls_info = self._analyzed.class_table.get(left_type.base)
        if cls_info is None:
            return None
        return cls_info.methods.get(magic)

    def resolved_operator_param_type(self, left_type, method):
        """Resolve an overload RHS type against its concrete receiver."""
        if method is None or not method.params:
            return None
        expected = method.params[0].type
        cls = self._analyzed.class_table.get(left_type.base) if left_type else None
        if cls and cls.generic_params and left_type.generic_args:
            expected = self._types.substitute_concrete_type(
                expected, dict(zip(cls.generic_params, left_type.generic_args))
            )
        return expected

    def _lower_prepared_overload(self, node, provenance: CallableProvenance):
        """Lower an overload whose RHS needs target-directed conversion."""
        left_type = self._analyzed.node_types.get(id(node.left))
        right_type = self._analyzed.node_types.get(id(node.right))
        method = self.overloaded_binary_method(left_type, node.op)
        expected = self.resolved_operator_param_type(left_type, method)
        if expected is None:
            return None
        if not self._calls.requires_string_conversion(expected, right_type):
            return None
        left = self.prepare_value(
            node.left,
            left_type,
            provenance,
        )
        right = self.prepare_value(
            node.right,
            expected,
            provenance,
        )
        operands = [
            CallOperand(
                node=node.left,
                type_expr=left.effective_type,
                c_type=self._types.render(left.effective_type),
                pin=bool(
                    self._ownership.borrowed_value_can_be_pinned(node.left)
                    and self._values.is_managed(left.effective_type)
                    and (not left.owned)
                ),
                owned=left.owned,
                lowered=left.value,
            ),
            CallOperand(
                node=node.right,
                type_expr=right.effective_type,
                c_type=self._types.render(right.effective_type),
                keep=bool(method.params[0].keep),
                owned=right.owned,
                lowered=right.value,
            ),
        ]
        evaluation = self._call_boundary.evaluate(operands)
        result_type = self._analyzed.node_types.get(id(node))
        call = self.lower_overloaded_values(
            left.effective_type,
            right.effective_type,
            node.op,
            evaluation.values[id(node.left)],
            evaluation.values[id(node.right)],
        )
        return self._call_boundary.materialize(
            evaluation,
            call,
            CallResultPlan(
                c_type=self._types.render(result_type),
                type_expr=result_type,
                owned=self._ownership.owns_result(node, provenance=provenance),
            ),
        )

    @staticmethod
    def _operator_method_name(op: str) -> str | None:
        return {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__div__",
            "%": "__mod__",
            "==": "__eq__",
            "!=": "__ne__",
            "<": "__lt__",
            ">": "__gt__",
            "<=": "__le__",
            ">=": "__ge__",
        }.get(op)

    def _lower_unary(self, node: UnaryExpr, provenance: CallableProvenance) -> IRExpr:
        if node.op == "&":
            self._callable_boundaries.reject_address_escape(node.operand, provenance)
        if node.op in {"++", "--"} and isinstance(node.operand, (FieldAccessExpr, IndexExpr)):
            target_nodes = [node.operand.obj]
            if isinstance(node.operand, IndexExpr):
                target_nodes.append(node.operand.index)
            result_type = self._analyzed.node_types.get(id(node))
            sequenced = self._sequence_operands(
                target_nodes,
                provenance,
                materialization=UnaryMaterialization(node),
                result_type=result_type,
                promote_result=bool(self._values.is_managed(result_type)),
            )
            if sequenced is not None:
                return sequenced
        if node.op not in {"++", "--", "&", "*"}:
            sequenced = self._sequence_operands(
                [node.operand],
                provenance,
                materialization=UnaryMaterialization(node),
                result_type=self._analyzed.node_types.get(id(node)),
            )
            if sequenced is not None:
                return sequenced
        return self._lower_unary_plain(
            node,
            provenance,
        )

    def _lower_unary_plain(self, node: UnaryExpr, provenance: CallableProvenance) -> IRExpr:
        op = node.op
        if op in {"++", "--"}:
            return IRUnaryOp(
                op=op,
                operand=self.lower_expr(
                    node.operand,
                    provenance,
                ),
                prefix=node.prefix,
            )
        operand = self.lower_expr(
            node.operand,
            provenance,
        )
        if op == "&":
            return IRAddressOf(expr=operand, source_expression=True)
        if op == "*":
            return IRDeref(expr=operand)
        if op == "-" and node.prefix:
            operand_type = self._analyzed.node_types.get(id(node.operand))
            if operand_type and operand_type.base in self._analyzed.class_table:
                cls_info = self._analyzed.class_table[operand_type.base]
                if "__neg__" in cls_info.methods:
                    if operand_type.generic_args:
                        cls_c_name = self._type_identity.specialization_symbol(
                            operand_type.base, operand_type.generic_args
                        )
                    else:
                        cls_c_name = operand_type.base
                    return IRCall(callee=f"{cls_c_name}___neg__", args=[operand])
        return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)

    def lower_optional_method_call(
        self,
        node: CallExpr,
        provenance: CallableProvenance,
    ) -> IRExpr:
        """Evaluate an optional receiver once and lower the guarded call lazily."""
        if not isinstance(node.callee, FieldAccessExpr) or not node.callee.optional:
            raise ValueError("optional-call lowering requires an optional field callee")
        receiver_node = node.callee.obj
        receiver_type = self._session.type_of(receiver_node)
        declaration = IRVarDecl(
            c_type=CType(text=self._types.render(receiver_type) if receiver_type is not None else "void*"),
            name=self._session.fresh_temp("__btrc_optional_receiver"),
        )
        self._session.record_declaration(declaration)
        receiver = IRVar(name=declaration.name)
        plain_callee = replace(node.callee, optional=False)
        plain_call = replace(node, callee=plain_callee)
        with self._session.operand_scope({id(receiver_node): receiver}):
            guarded = self.lower_call_plan(
                self._calls.plan(plain_call),
                provenance,
            )
        result_type = self._session.type_of(node)
        return IRStmtExpr(
            stmts=[declaration],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(
                        left=receiver,
                        op="=",
                        right=self.lower_expr(
                            receiver_node,
                            provenance,
                        ),
                    ),
                    IRTernary(
                        condition=IRBinOp(
                            left=receiver,
                            op="!=",
                            right=IRLiteral(text="NULL"),
                        ),
                        true_expr=guarded,
                        false_expr=self._types.optional_zero_value(result_type),
                    ),
                ]
            ),
        )

    def lower_long_string_concat(self, node, provenance: CallableProvenance):
        """Lower a long left-associated chain as one flat comma sequence."""
        leaves = self._left_chain_leaves(node)
        if len(leaves) < _FLAT_CHAIN_MIN_TERMS:
            return None
        result_type = self._analyzed.node_types.get(id(node))
        c_type = self._types.render(result_type)
        declarations: list[IRVarDecl] = []
        sequence = []
        values = []
        leaf_types = []
        owned = []
        for leaf in leaves:
            leaf_type = self._analyzed.node_types.get(id(leaf)) or result_type
            declaration = self._temporary("__btrc_concat_part", c_type)
            declarations.append(declaration)
            value = IRVar(name=declaration.name)
            values.append(value)
            leaf_types.append(leaf_type)
            owned.append(self._ownership.owns_result(leaf, provenance=provenance))
        initial_pins = self._operand_order.source_order_pin_flags(leaves[:2], leaf_types[:2], owned[:2])
        accumulator_decl = self._temporary("__btrc_concat_acc", c_type)
        next_decl = self._temporary("__btrc_concat_next", c_type)
        result_decl = self._temporary("__btrc_concat_result", c_type)
        declarations.extend([accumulator_decl, next_decl, result_decl])
        accumulator = IRVar(name=accumulator_decl.name)
        next_value = IRVar(name=next_decl.name)
        result = IRVar(name=result_decl.name)
        self._evaluate_leaf(
            leaves[0],
            leaf_types[0],
            declarations[0],
            values[0],
            owned[0],
            initial_pins[0],
            declarations,
            sequence,
            provenance,
        )
        self._evaluate_leaf(
            leaves[1],
            leaf_types[1],
            declarations[1],
            values[1],
            owned[1],
            False,
            declarations,
            sequence,
            provenance,
        )
        sequence.append(IRBinOp(left=accumulator, op="=", right=self._concat_call(values[0], values[1])))
        self._register_cleanup(accumulator_decl, result_type, declarations, sequence, "__btrc_concat_acc_cleanup")
        self._release_leaf(values[0], leaf_types[0], bool(owned[0] or initial_pins[0]), sequence)
        self._release_leaf(values[1], leaf_types[1], owned[1], sequence)
        for index in range(2, len(values)):
            leaf = values[index]
            leaf_type = leaf_types[index]
            self._evaluate_leaf(
                leaves[index],
                leaf_type,
                declarations[index],
                leaf,
                owned[index],
                False,
                declarations,
                sequence,
                provenance,
            )
            sequence.append(IRBinOp(left=next_value, op="=", right=self._concat_call(accumulator, leaf)))
            sequence.extend(
                [
                    self._lifetime.release_value(accumulator, result_type),
                    IRBinOp(left=accumulator, op="=", right=IRLiteral(text="NULL")),
                ]
            )
            self._release_leaf(leaf, leaf_type, owned[index], sequence)
            sequence.extend(
                [
                    IRBinOp(left=accumulator, op="=", right=next_value),
                    IRBinOp(left=next_value, op="=", right=IRLiteral(text="NULL")),
                ]
            )
        sequence.extend(
            [
                IRBinOp(left=result, op="=", right=accumulator),
                IRBinOp(left=accumulator, op="=", right=IRLiteral(text="NULL")),
                result,
            ]
        )
        return IRStmtExpr(stmts=declarations, result=IRCommaExpr(expressions=sequence))

    def _left_chain_leaves(self, node):
        rights = []
        cursor = node
        while self._is_scalar_concat(cursor):
            rights.append(cursor.right)
            cursor = cursor.left
        rights.reverse()
        return [cursor, *rights]

    def _is_scalar_concat(self, node) -> bool:
        if not isinstance(node, BinaryExpr) or node.op != "+":
            return False
        types = self._analyzed.node_types
        return all(self._values.is_string(types.get(id(value))) for value in (node, node.left, node.right))

    def _temporary(self, prefix: str, c_type: str) -> IRVarDecl:
        declaration = IRVarDecl(
            c_type=CType(text=c_type), name=self._session.fresh_temp(prefix), init=IRLiteral(text="NULL")
        )
        self._session.function_declarations.append(declaration)
        return declaration

    def _register_cleanup(self, declaration, type_expr, declarations, sequence, prefix):
        cleanup_declarations, cleanup_expressions = self._lifetime.cleanup_registration(
            declaration, type_expr, prefix, active=self._cleanup_scope.exception_cleanup_active()
        )
        declarations.extend(cleanup_declarations)
        sequence.extend(cleanup_expressions)

    def _evaluate_leaf(
        self,
        node,
        type_expr,
        declaration,
        value,
        owned,
        pinned,
        declarations,
        sequence,
        provenance: CallableProvenance,
    ) -> None:
        sequence.append(
            IRBinOp(
                left=value,
                op="=",
                right=self.lower_expr(
                    node,
                    provenance,
                ),
            )
        )
        if pinned:
            sequence.append(self._lifetime.retain_value(value, type_expr))
        if owned or pinned:
            self._register_cleanup(declaration, type_expr, declarations, sequence, "__btrc_concat_part_cleanup")

    def _release_leaf(self, value, type_expr, owned: bool, sequence) -> None:
        if not owned:
            return
        sequence.extend(
            [self._lifetime.release_value(value, type_expr), IRBinOp(left=value, op="=", right=IRLiteral(text="NULL"))]
        )

    def _concat_call(self, left, right):
        self._session.require_helper("__btrc_strcat")
        self._session.require_helper("__btrc_str_track")
        return IRCall(
            callee="__btrc_str_track",
            args=[IRCall(callee="__btrc_strcat", args=[left, right], helper_ref="__btrc_strcat")],
            helper_ref="__btrc_str_track",
        )
