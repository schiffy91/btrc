"""Cohesive iteration IR lowering owner."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.types import TypeIdentity, TypeSystem
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRStatementSequence,
    IRStmt,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    Block,
    CallExpr,
    CForStmt,
    ForInitVar,
    Identifier,
    TypeExpr,
    VarDeclStmt,
)

from .ownership import ManagedLocal
from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import CallableFlowSnapshot, CallableLoopFlow, CallableProvenance
    from .expressions import PreparedProjectionStorage, StabilizedProjectionStorage
    from .ownership import (
        CleanupScopeState,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
    )
    from .session import LoweringSession
    from .storage import StorageLowerer


@dataclass(frozen=True)
class IterationBinding:
    """One value produced by ``iterGet``/``iterValueAt`` per iteration."""

    name: str
    c_type: str
    type_expr: TypeExpr | None
    value: IRExpr
    owned: bool


@dataclass(slots=True)
class IterationPlan:
    """Structured loop shell whose source body is lowered by StatementLowerer."""

    source_body: Block | None
    prefix: list[IRStmt]
    bindings: tuple[IterationBinding, ...]
    init: IRStmt | None
    condition: IRExpr
    update: IRExpr | None
    owners: tuple[ManagedLocal, ...] = ()


@dataclass(slots=True)
class CForPlan:
    """Bounded state for one C-style loop lexical transaction."""

    source: CForStmt
    initializer: VarDeclStmt | None
    prefix: list[IRStmt]
    init: IRStmt | None
    condition: IRExpr | None = None
    update: IRExpr | None = None
    backedge_states: tuple[CallableFlowSnapshot, ...] = ()
    cleanup_marker: str | None = None
    managed_scope_active: bool = False
    local_scope_active: bool = False
    c_scope_active: bool = False


class IterationLowerer:
    """Own iteration lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        type_identity: TypeIdentity,
        storage: StorageLowerer,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cleanup_scope: CleanupScopeState,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._type_identity = type_identity
        self._storage = storage
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cleanup_scope = cleanup_scope

    def plan_fixed_array_for_in(
        self,
        node,
        array_type: TypeExpr,
        lowered_iterable: IRExpr,
        provenance: CallableProvenance,
        projection_storage: PreparedProjectionStorage | None = None,
    ) -> IterationPlan:
        """Plan a fixed-array loop without traversing its source body."""
        prefix: list[IRStmt] = []
        owners: list[ManagedLocal] = []
        if projection_storage is not None:
            prefix.extend(projection_storage.declarations)
            prefix.extend(IRExprStmt(expr=assignment) for assignment in projection_storage.assignments)
            lowered_iterable = projection_storage.value
            for storage in projection_storage.storage:
                owner = self.begin_projection_storage_owner(storage, prefix, provenance)
                if owner is not None:
                    owners.append(owner)
        iterable = self._session.fresh_temp("__iter")
        length = self._session.fresh_temp("__n")
        index = self._session.fresh_temp("__i")
        prefix.extend(
            [
                IRVarDecl(
                    c_type=CType(text="size_t"),
                    name=length,
                    init=self.fixed_array_iteration_length(node.iterable, lowered_iterable),
                ),
                IRVarDecl(c_type=CType(text=self._types.render(array_type)), name=iterable, init=lowered_iterable),
            ]
        )
        owner = self.begin_owned_iterable(node.iterable, array_type, iterable, prefix, provenance)
        if owner is not None:
            owners.append(owner)
        element_type = TypeSystem.strip_outer_storage(array_type, array=True)
        return IterationPlan(
            source_body=node.body,
            prefix=prefix,
            bindings=(
                IterationBinding(
                    name=node.var_name,
                    c_type=self._types.render(element_type),
                    type_expr=element_type,
                    value=IRIndex(obj=IRVar(name=iterable), index=IRVar(name=index)),
                    owned=False,
                ),
            ),
            init=IRVarDecl(c_type=CType(text="size_t"), name=index, init=IRLiteral(text="0")),
            condition=IRBinOp(left=IRVar(name=index), op="<", right=IRVar(name=length)),
            update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
            owners=tuple(owners),
        )

    @staticmethod
    def fixed_array_capacity(array):
        """Return ``sizeof(array) / sizeof(array[0])`` as structured IR."""
        return IRBinOp(
            left=IRSizeof(operand=array), op="/", right=IRSizeof(operand=IRIndex(obj=array, index=IRLiteral(text="0")))
        )

    def fixed_array_iteration_length(self, expression, array):
        """Prefer a GPU result's logical length over its physical safety bound."""
        if isinstance(expression, Identifier):
            logical = self._storage.local_gpu_array_length(expression.name)
            if logical is not None:
                return logical
        return self.fixed_array_capacity(array)

    def is_fixed_array_iterable(self, expression) -> bool:
        """Whether analyzer facts require a physical fixed-array extent."""
        return id(expression) in self._analyzed.array_iteration_capacity_ids

    def emit_iteration_bindings(self, bindings, provenance: CallableProvenance) -> list[IRStmt]:
        """Declare bindings inside the body scope and register owned results."""
        result: list[IRStmt] = []
        for binding in bindings:
            binding_c_name = self._ownership.declare_local_ownership(binding.name, provenance)
            provenance.bind_borrowed(binding.name, binding.type_expr)
            declaration = IRVarDecl(c_type=CType(text=binding.c_type), name=binding_c_name, init=binding.value)
            self._session.function_declarations.append(declaration)
            result.append(declaration)
            result.append(IRExprStmt(expr=IRVar(name=binding_c_name)))
            type_expr = binding.type_expr
            managed = binding.owned and self._values.is_managed(type_expr)
            if managed:
                runtime_type = self._values.runtime_name(type_expr)
                self._ownership.register_managed_var(
                    binding.name,
                    runtime_type,
                    type_expr,
                    provenance,
                    cycle_seed=not self._values.is_string(type_expr),
                )
                self._ownership.declare_local_ownership(binding.name, provenance, runtime_type)
                self._lifetime.register_named_cleanup(binding_c_name, runtime_type, result)
        return result

    def _plan_range_for(
        self,
        var_name: str,
        lowered_args: list[IRExpr],
        body: Block | None,
        provenance: CallableProvenance,
    ) -> IterationPlan:
        """Plan ``for x in range(...)`` after expression operands are lowered."""
        start = IRLiteral(text="0")
        end = IRLiteral(text="0")
        step = IRLiteral(text="1")
        if lowered_args:
            if len(lowered_args) == 1:
                end = lowered_args[0]
            else:
                start = lowered_args[0]
                end = lowered_args[1]
            if len(lowered_args) >= 3:
                step = lowered_args[2]
        c_name = self._ownership.declare_local_ownership(var_name, provenance)
        provenance.shadow(var_name)
        condition = IRBinOp(left=IRVar(name=c_name), op="<", right=end)
        update: IRExpr = IRUnaryOp(op="++", operand=IRVar(name=c_name), prefix=False)
        if len(lowered_args) >= 3:
            condition = IRTernary(
                condition=IRBinOp(left=step, op=">", right=IRLiteral(text="0")),
                true_expr=condition,
                false_expr=IRBinOp(left=IRVar(name=c_name), op=">", right=end),
            )
            update = IRBinOp(left=IRVar(name=c_name), op="+=", right=step)
        return IterationPlan(
            source_body=body,
            prefix=[],
            bindings=(),
            init=IRVarDecl(c_type=CType(text="int"), name=c_name, init=start),
            condition=condition,
            update=update,
        )

    @contextmanager
    def c_for_scope(self, node: CForStmt, provenance: CallableProvenance):
        """Own the lexical lifetime around one C-style loop transaction."""
        enclosing = provenance.begin_scope()
        initializer = node.init.var_decl if isinstance(node.init, ForInitVar) else None
        plan = CForPlan(source=node, initializer=initializer, prefix=[], init=None)
        try:
            if isinstance(node.init, ForInitVar):
                plan.cleanup_marker = self._cleanup_scope.push()
                self._ownership.push_managed_scope()
                plan.managed_scope_active = True
                self._ownership.push_local_ownership_scope()
                plan.local_scope_active = True
                self._session.c_array_scopes.append({})
                plan.c_scope_active = True
            yield plan
        finally:
            if plan.managed_scope_active:
                self._ownership.pop_managed_scope()
            if plan.c_scope_active:
                self._session.c_array_scopes.pop()
            if plan.local_scope_active:
                self._ownership.pop_local_ownership_scope()
            if plan.cleanup_marker is not None:
                self._cleanup_scope.pop()
            provenance.finish_scope(enclosing)

    @contextmanager
    def c_for_condition_scope(self, plan: CForPlan, provenance: CallableProvenance):
        """Validate callable flow across the explicitly lowered condition."""
        entry = provenance.snapshot()
        yield
        if plan.source.condition is not None:
            provenance.require_loop_edge_invariant(
                entry,
                provenance.snapshot(),
                edge="condition",
            )

    @contextmanager
    def c_for_update_scope(
        self,
        plan: CForPlan,
        loop_flow: CallableLoopFlow,
        provenance: CallableProvenance,
    ):
        """Position callable flow for an explicitly lowered loop update."""
        if loop_flow.backedge_states:
            provenance.restore(provenance.merge_flows(*loop_flow.backedge_states))
            yield
            plan.backedge_states = (provenance.snapshot(),)
        else:
            with provenance.isolated_flow():
                yield
            plan.backedge_states = ()

    def materialize_c_for(
        self,
        plan: CForPlan,
        body: IRBlock,
        loop_flow: CallableLoopFlow,
        provenance: CallableProvenance,
    ) -> IRStmt:
        """Materialize a C-style loop from explicitly lowered components."""
        backedges = plan.backedge_states if plan.source.update is not None else loop_flow.backedge_states
        provenance.complete_loop(
            loop_flow,
            backedge_states=backedges,
            condition_can_exit=plan.source.condition is not None,
        )
        loop = IRFor(
            init=plan.init,
            condition=plan.condition or IRLiteral(text="1"),
            update=IRCast(target_type=CType(text="void"), expr=plan.update) if plan.update is not None else None,
            body=body,
            realtime_bounded=id(plan.source) in self._analyzed.realtime_bounded_loop_ids,
        )
        if not plan.managed_scope_active:
            return loop
        scoped_statements = [*plan.prefix, loop]
        sequence = IRStatementSequence(scoped_statements)
        falls_through = sequence.may_fall_through()
        managed = self._ownership.pop_managed_scope()
        plan.managed_scope_active = False
        marker_active = self._cleanup_scope.is_active(plan.cleanup_marker)
        marker_referenced = falls_through or sequence.references_variable(plan.cleanup_marker or "")
        if marker_active and marker_referenced:
            scoped_statements[:0] = self._cleanup_scope.entry(plan.cleanup_marker)
        if falls_through:
            scoped_statements.extend(self._lifetime.release_scope(managed))
            if marker_active and marker_referenced:
                scoped_statements.extend(self._cleanup_scope.exit(plan.cleanup_marker))
        return IRBlock(stmts=scoped_statements)

    def iterable_result_is_owned(self, expression, type_expr, provenance: CallableProvenance) -> bool:
        """Whether the loop receives a fresh managed iterable reference."""
        if not self._values.is_managed(type_expr):
            return False
        return self._ownership.lowered_result_is_owned(expression, provenance=provenance)

    def begin_owned_iterable(
        self,
        expression,
        type_expr,
        name: str,
        prefix: list[IRStmt],
        provenance: CallableProvenance,
    ) -> ManagedLocal | None:
        """Own one managed iterable for the complete lowered loop lifetime.

        A fresh expression transfers its existing +1 into the synthetic local.
        A borrowed expression is retained after its exact-once hoist.  Registering
        either form before lowering the body makes return/throw cleanup see it,
        while the loop control marker keeps it live across continue and break.
        """
        if not self._values.is_managed(type_expr):
            return None
        return self._begin_managed_iteration_owner(
            name,
            type_expr,
            prefix,
            provenance,
            retain=not self.iterable_result_is_owned(expression, type_expr, provenance),
        )

    def begin_projection_storage_owner(
        self,
        storage: StabilizedProjectionStorage,
        prefix: list[IRStmt],
        provenance: CallableProvenance,
    ) -> ManagedLocal | None:
        """Adopt or keep one stabilized backing root for the complete loop."""
        if not self._values.is_managed(storage.type_expr):
            return None
        if not (storage.operand.owned or storage.operand.keep):
            raise CodegenError("managed projection storage has no ownership contract")
        return self._begin_managed_iteration_owner(
            storage.value.name,
            storage.type_expr,
            prefix,
            provenance,
            retain=storage.operand.keep,
        )

    def _begin_managed_iteration_owner(
        self,
        name: str,
        type_expr: TypeExpr,
        prefix: list[IRStmt],
        provenance: CallableProvenance,
        *,
        retain: bool,
    ) -> ManagedLocal:
        """Register one stabilized managed value across loop control exits."""
        if retain:
            prefix.append(IRExprStmt(expr=self._lifetime.retain_value(IRVar(name=name), type_expr)))
        owner = ManagedLocal(
            name=name,
            type_name=self._values.runtime_name(type_expr),
            cycle_seed=not self._values.is_string(type_expr),
            value_type=type_expr,
        )
        self._ownership.register_managed_var(
            owner.name,
            owner.type_name,
            type_expr,
            provenance,
            cycle_seed=owner.cycle_seed,
        )
        self._lifetime.register_named_cleanup(owner.name, owner.type_name, prefix)
        return owner

    def finish_owned_iterable(self, owner: ManagedLocal | None, provenance: CallableProvenance) -> list[IRStmt]:
        """Release one owned hoist after exhaustion or a loop ``break``."""
        if owner is None:
            return []
        self._ownership.unregister_managed_var(owner.name, provenance)
        result = self._lifetime.release_scope([owner])
        result.append(IRAssign(target=IRVar(name=owner.name), value=IRLiteral(text="NULL")))
        return result

    def plan_string_for_in(
        self,
        node,
        iterable: IRExpr,
        var_name: str,
        provenance: CallableProvenance,
    ) -> IterationPlan:
        """Plan a string loop without traversing its source body."""
        index = self._session.fresh_temp("__i")
        temp = self._session.fresh_temp("__iter")
        iter_var = IRVar(name=temp)
        prefix = [IRVarDecl(c_type=CType(text="char*"), name=temp, init=iterable)]
        iterable_type = self._session.type_of(node.iterable)
        owner = self.begin_owned_iterable(node.iterable, iterable_type, temp, prefix, provenance)
        return IterationPlan(
            source_body=node.body,
            prefix=prefix,
            bindings=(
                IterationBinding(
                    name=var_name,
                    c_type="char",
                    type_expr=None,
                    value=IRIndex(obj=iter_var, index=IRVar(name=index)),
                    owned=False,
                ),
            ),
            init=IRVarDecl(c_type=CType(text="int"), name=index, init=IRLiteral(text="0")),
            condition=IRBinOp(
                left=IRIndex(obj=iter_var, index=IRVar(name=index)),
                op="!=",
                right=IRLiteral(text="'\\0'"),
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
            owners=(owner,) if owner is not None else (),
        )

    def plan_span_for_in(
        self,
        node,
        iterable: IRExpr,
        span_type: TypeExpr,
        provenance: CallableProvenance,
    ) -> IterationPlan:
        """Plan bounded iteration over one already-proven nonescaping view."""
        temporary = self._session.fresh_temp("__span")
        index = self._session.fresh_temp("__i")
        element = span_type.generic_args[0]
        view = IRVar(name=temporary)
        return IterationPlan(
            source_body=node.body,
            prefix=[IRVarDecl(c_type=CType(text=self._types.render(span_type)), name=temporary, init=iterable)],
            bindings=(
                IterationBinding(
                    name=node.var_name,
                    c_type=self._types.render(element),
                    type_expr=element,
                    value=IRIndex(
                        obj=IRFieldAccess(obj=view, field="data", arrow=False),
                        index=IRVar(name=index),
                    ),
                    owned=False,
                ),
            ),
            init=IRVarDecl(c_type=CType(text="size_t"), name=index, init=IRLiteral(text="0")),
            condition=IRBinOp(
                left=IRVar(name=index),
                op="<",
                right=IRFieldAccess(obj=view, field="length", arrow=False),
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=index), prefix=False),
        )

    @staticmethod
    def is_range_loop(node) -> bool:
        """Whether one for-in source uses the intrinsic range iterator."""
        iterable = node.iterable
        return bool(
            isinstance(iterable, CallExpr)
            and isinstance(iterable.callee, Identifier)
            and iterable.callee.name == "range"
        )

    @contextmanager
    def for_in_scope(
        self,
        node,
        lowered_iterable: IRExpr | None,
        lowered_range_arguments: list[IRExpr],
        provenance: CallableProvenance,
        *,
        projection_storage: PreparedProjectionStorage | None = None,
    ):
        """Build one loop shell while retaining only its bounded lexical scope."""
        iterable = node.iterable
        var_name = node.var_name
        var_name2 = getattr(node, "var_name2", None)
        if self.is_range_loop(node):
            self._ownership.push_local_ownership_scope()
            enclosing_callables = provenance.begin_scope()
            try:
                yield self._plan_range_for(var_name, lowered_range_arguments, node.body, provenance)
            finally:
                provenance.finish_scope(enclosing_callables)
                self._ownership.pop_local_ownership_scope()
            return
        if lowered_iterable is None:
            raise CodegenError("for-in iterable was not materialized")
        iter_type = self._session.type_of(iterable)
        if self.is_fixed_array_iterable(iterable):
            if iter_type is None:
                raise CodegenError("fixed-array iteration has no concrete type")
            yield self.plan_fixed_array_for_in(
                node,
                iter_type,
                lowered_iterable,
                provenance,
                projection_storage,
            )
            return
        if iter_type and iter_type.base == "Span" and len(iter_type.generic_args) == 1:
            yield self.plan_span_for_in(node, lowered_iterable, iter_type, provenance)
            return
        if iter_type:
            cls_info = self._analyzed.class_table.get(iter_type.base)
            if cls_info and "iterLen" in cls_info.methods and ("iterGet" in cls_info.methods):
                yield self._plan_iterable_for_in(
                    node,
                    lowered_iterable,
                    iter_type,
                    cls_info,
                    var_name,
                    var_name2,
                    provenance,
                )
                return
        if iter_type and iter_type.base == "string":
            yield self.plan_string_for_in(node, lowered_iterable, var_name, provenance)
            return
        idx = self._session.fresh_temp("__i")
        tmp_iter = self._session.fresh_temp("__iter")
        iter_c_type = "void*"
        if iter_type:
            iter_c_type = self._types.render(iter_type)
            if not iter_c_type.endswith("*"):
                iter_c_type += "*"
        if iter_type and iter_type.generic_args:
            elem_c = self._iter_value_c(iter_type.generic_args[0])
        else:
            elem_c = "int"
        prefix = [IRVarDecl(c_type=CType(text=iter_c_type), name=tmp_iter, init=lowered_iterable)]
        owner = self.begin_owned_iterable(iterable, iter_type, tmp_iter, prefix, provenance)
        data_expr = IRFieldAccess(obj=IRVar(name=tmp_iter), field="data", arrow=True)
        elem_type = iter_type.generic_args[0] if iter_type and iter_type.generic_args else None
        yield IterationPlan(
            source_body=node.body,
            prefix=prefix,
            bindings=(
                IterationBinding(
                    name=var_name,
                    c_type=elem_c,
                    type_expr=elem_type,
                    value=IRIndex(obj=data_expr, index=IRVar(name=idx)),
                    owned=False,
                ),
            ),
            init=IRVarDecl(c_type=CType(text="int"), name=idx, init=IRLiteral(text="0")),
            condition=IRBinOp(
                left=IRVar(name=idx),
                op="<",
                right=IRFieldAccess(obj=IRVar(name=tmp_iter), field="len", arrow=True),
            ),
            update=IRUnaryOp(op="++", operand=IRVar(name=idx), prefix=False),
            owners=(owner,) if owner is not None else (),
        )

    def _plan_iterable_for_in(
        self,
        node,
        ir_iter: IRExpr,
        iter_type: TypeExpr,
        cls_info,
        var_name: str,
        var_name2: str | None,
        provenance: CallableProvenance,
    ) -> IterationPlan:
        """Plan an Iterable-protocol loop without traversing its source body."""
        mangled = (
            self._type_identity.specialization_symbol(iter_type.base, iter_type.generic_args)
            if iter_type.generic_args
            else iter_type.base
        )
        tmp_iter = self._session.fresh_temp("__iter")
        iter_c_type = self._types.render(iter_type)
        if not iter_c_type.endswith("*"):
            iter_c_type += "*"
        hoist_decl = IRVarDecl(c_type=CType(text=iter_c_type), name=tmp_iter, init=ir_iter)
        ir_iter = IRVar(name=tmp_iter)
        stmts: list[IRStmt] = [hoist_decl]
        owner = self.begin_owned_iterable(node.iterable, iter_type, hoist_decl.name, stmts, provenance)
        idx = self._session.fresh_temp("__i")
        n_var = self._session.fresh_temp("__n")
        elem_type = self._iter_method_return_type(cls_info, iter_type, "iterGet")
        elem_c = self._iter_value_c(elem_type)
        bindings = [
            IterationBinding(
                name=var_name,
                c_type=elem_c,
                type_expr=elem_type,
                value=IRCall(callee=f"{mangled}_iterGet", args=[ir_iter, IRVar(name=idx)]),
                owned=True,
            )
        ]
        if var_name2 and "iterValueAt" in cls_info.methods:
            value_type = self._iter_method_return_type(cls_info, iter_type, "iterValueAt")
            v_c = self._iter_value_c(value_type)
            bindings.append(
                IterationBinding(
                    name=var_name2,
                    c_type=v_c,
                    type_expr=value_type,
                    value=IRCall(callee=f"{mangled}_iterValueAt", args=[ir_iter, IRVar(name=idx)]),
                    owned=True,
                )
            )
        stmts.append(
            IRVarDecl(c_type=CType(text="int"), name=n_var, init=IRCall(callee=f"{mangled}_iterLen", args=[ir_iter]))
        )
        return IterationPlan(
            source_body=node.body,
            prefix=stmts,
            bindings=tuple(bindings),
            init=IRVarDecl(c_type=CType(text="int"), name=idx, init=IRLiteral(text="0")),
            condition=IRBinOp(left=IRVar(name=idx), op="<", right=IRVar(name=n_var)),
            update=IRUnaryOp(op="++", operand=IRVar(name=idx), prefix=False),
            owners=(owner,) if owner is not None else (),
        )

    def materialize_for_in(
        self,
        plan: IterationPlan,
        body: IRBlock,
        loop_flow: CallableLoopFlow,
        provenance: CallableProvenance,
    ) -> list[IRStmt]:
        """Complete callable flow and install an explicitly lowered loop body."""
        provenance.complete_loop(loop_flow, condition_can_exit=True)
        result = [
            *plan.prefix,
            IRFor(
                init=plan.init,
                condition=plan.condition,
                update=plan.update,
                body=body,
            ),
        ]
        for owner in reversed(plan.owners):
            result.extend(self.finish_owned_iterable(owner, provenance))
        return result

    def _iter_value_c(self, t: TypeExpr | None) -> str:
        c_type = self._types.render(t)
        if t and t.base in self._analyzed.class_table and (not c_type.endswith("*")):
            return f"{c_type}*"
        return c_type

    def _iter_method_return_type(self, cls_info, iter_type, method_name):
        """Resolve an iterable protocol method for one concrete instance."""
        method = cls_info.methods[method_name]
        if not cls_info.generic_params:
            return method.return_type
        substitutions = dict(zip(cls_info.generic_params, iter_type.generic_args))
        return self._types.substitute_concrete_type(method.return_type, substitutions)
