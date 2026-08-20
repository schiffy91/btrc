"""Cohesive statements IR lowering owner."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRBreak,
    IRCall,
    IRCast,
    IRContinue,
    IRDoWhile,
    IRExpr,
    IRExprStmt,
    IRLiteral,
    IRStatementSequence,
    IRStmt,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from src.compiler.python.syntax.ast.generated import (
    Block,
    BreakStmt,
    CallExpr,
    CForStmt,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    ExprStmt,
    FieldAccessExpr,
    ForInitExpr,
    ForInStmt,
    Identifier,
    IfStmt,
    IndexExpr,
    KeepStmt,
    NullLiteral,
    ParallelForStmt,
    ReleaseStmt,
    ReturnStmt,
    SelfExpr,
    SpawnExpr,
    SwitchStmt,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)

from .calls import CallableLoopFlow
from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import CallableProvenance, CallableStorageBoundary
    from .control_flow import ControlFlowLowerer
    from .exceptions import ExceptionLowerer
    from .expressions import ExpressionLowerer
    from .gpu import GpuLowerer
    from .iteration import IterationLowerer
    from .ownership import (
        CleanupScopeState,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
    )
    from .session import LoweringSession
    from .storage import StorageLowerer


class StatementLowerer:
    """Own statements lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        expressions: ExpressionLowerer,
        storage: StorageLowerer,
        ownership: OwnershipLowerer,
        callable_boundaries: CallableStorageBoundary,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cleanup_scope: CleanupScopeState,
        control_flow: ControlFlowLowerer,
        exceptions: ExceptionLowerer,
        iteration: IterationLowerer,
        gpu: GpuLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._expressions = expressions
        self._storage = storage
        self._ownership = ownership
        self._callable_boundaries = callable_boundaries
        self._values = values
        self._lifetime = lifetime
        self._cleanup_scope = cleanup_scope
        self._control_flow = control_flow
        self._exceptions = exceptions
        self._iteration = iteration
        self._gpu = gpu

    def lower_assert_statement(
        self,
        expression,
        provenance: CallableProvenance,
    ) -> list[IRStmt] | None:
        """Materialize a source ``assert`` argument before the C macro boundary.

        The C macro stringifies its argument, so a deeply lowered expression can
        exceed C11's required string-literal capacity even when formatted across
        physical lines.  Materialization also keeps btrc call semantics deliberate:
        the source argument is evaluated exactly once, including under ``NDEBUG``.
        """
        hosted = not self._session.freestanding and "assert" not in self._analyzed.function_table
        if not hosted or not StatementLowerer._is_assert_call(expression):
            return None
        name = self._session.fresh_temp("__btrc_assert_condition")
        declaration = IRVarDecl(
            c_type=CType(text="bool"),
            name=name,
            init=self._expressions.lower_expr(
                expression.args[0],
                provenance,
            ),
        )
        self._session.record_declaration(declaration)
        value = IRVar(name=name)
        return [
            declaration,
            IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=value)),
            IRExprStmt(expr=IRCall(callee="assert", args=[value])),
        ]

    @staticmethod
    def _is_assert_call(expression) -> bool:
        return (
            isinstance(expression, CallExpr)
            and isinstance(expression.callee, Identifier)
            and (expression.callee.name == "assert")
            and (len(expression.args) == 1)
            and (not any(expression.arg_names))
        )

    def lower_block(
        self,
        block: Block | None,
        provenance: CallableProvenance,
        *,
        iteration_bindings=(),
        local_bindings=(),
        callable_bindings=(),
        callable_abis=(),
    ) -> IRBlock:
        """Lower a btrc Block to an IRBlock."""
        if block is None:
            return IRBlock()
        local_bindings = tuple(local_bindings)
        iteration_bindings = tuple(iteration_bindings)
        enclosing_callables = provenance.begin_scope()
        marker = self._cleanup_scope.push()
        self._ownership.push_managed_scope()
        self._ownership.push_local_ownership_scope()
        c_bindings = {name: False for name in local_bindings}
        c_bindings.update({binding.name: False for binding in iteration_bindings})
        self._session.c_array_scopes.append(c_bindings)
        stmts = []
        try:
            for name in local_bindings:
                self._ownership.declare_local_ownership(name, provenance)
                provenance.shadow(name)
            for binding in callable_bindings:
                if isinstance(binding, tuple):
                    name, type_expr = binding
                else:
                    name, type_expr = (binding.name, binding.type)
                provenance.bind_borrowed(name, type_expr)
            for binding, return_abi in callable_abis:
                provenance.bind_with_abi(binding.name, binding.type, return_abi)
            if iteration_bindings:
                stmts.extend(self._iteration.emit_iteration_bindings(iteration_bindings, provenance))
            for statement in block.statements:
                self._emit_line_marker(statement, stmts)
                stmts.extend(
                    self.lower_stmt(
                        statement,
                        provenance,
                    )
                )
            sequence = IRStatementSequence(stmts)
            falls_through = sequence.may_fall_through()
            managed = self._ownership.pop_managed_scope()
            marker_active = self._cleanup_scope.is_active(marker)
            marker_referenced = falls_through or sequence.references_variable(marker or "")
            if marker_active and marker_referenced:
                stmts[:0] = self._cleanup_scope.entry(marker)
            if falls_through:
                stmts.extend(self._lifetime.release_scope(managed))
                if marker_active and marker_referenced:
                    stmts.extend(self._cleanup_scope.exit(marker))
        finally:
            self._session.c_array_scopes.pop()
            self._ownership.pop_local_ownership_scope()
            self._cleanup_scope.pop()
            provenance.finish_scope(enclosing_callables)
        return IRBlock(stmts=stmts)

    def _emit_line_marker(self, ast_stmt, out: list) -> None:
        """In --debug mode, prepend a ``#line`` marker mapping this statement back to
        its .btrc source, so the compiled binary's DWARF points at btrc source."""
        if not (self._session.debug and self._session.source_map):
            return
        line = getattr(ast_stmt, "line", 0)
        if not line:
            return
        mapped = self._session.source_map.combined(line)
        if not mapped:
            return
        from ..nodes import IRLineMarker

        out.append(IRLineMarker(file=mapped[0], line=mapped[1]))

    def lower_return(
        self,
        node: ReturnStmt,
        provenance: CallableProvenance,
    ) -> list[IRStmt]:
        """Lower the source value, then materialize its ownership return plan."""
        self._callable_boundaries.reject_persistent_escape(
            self._session.current_return_type,
            node.value,
            "a function return",
            provenance,
        )
        plan = self._ownership.plan_return(node, provenance)
        if node.value is None:
            return self._ownership.materialize_return(plan, None, provenance)
        prepared = self._expressions.prepare_value(
            node.value,
            self._session.current_return_type,
            provenance,
        )
        return self._ownership.materialize_return(
            plan,
            prepared.value,
            provenance,
            effective_type=prepared.effective_type,
            owned=prepared.owned,
            converted=prepared.converted,
        )

    def lower_declaration(
        self,
        node: VarDeclStmt,
        provenance: CallableProvenance,
    ) -> list[IRStmt]:
        """Lower declaration operands before storage materialization."""
        plan = self._storage.plan_declaration(
            node,
            provenance,
        )
        if (
            isinstance(plan.initializer, CallExpr)
            and self._gpu.output_gpu_call_name(plan.initializer, provenance) is not None
        ):
            size_setup: list[IRStmt] = []
            explicit_size = None
            if plan.array_size is not None:
                size_declaration = IRVarDecl(
                    c_type=CType(text="int"),
                    name=self._session.fresh_temp("__gpu_output_size"),
                    init=self._expressions.lower_expr(
                        plan.array_size,
                        provenance,
                    ),
                )
                self._session.record_declaration(size_declaration)
                size_setup.append(size_declaration)
                explicit_size = IRVar(name=size_declaration.name)
            output = self._gpu.lower_gpu_output_declaration(
                plan.initializer,
                IRVar(name=plan.c_name),
                self._expressions.lower_gpu_arguments(plan.initializer, provenance),
                provenance,
            )
            length_setup: tuple[IRStmt, ...] = ()
            if explicit_size is not None:
                array_size = self._storage.materialize_array_size(plan, explicit_size)
                logical_size: IRExpr | None = explicit_size
            else:
                dispatch_bound = self._storage.materialize_dispatch_length(output.array_length or IRLiteral(text="0"))
                length_setup = dispatch_bound.setup
                array_size = dispatch_bound.physical
                logical_size = dispatch_bound.logical
            declaration = self._storage.materialize_declaration(
                plan,
                provenance,
                initializer=None,
                array_size=array_size,
                logical_length=logical_size,
            )
            return [
                *size_setup,
                *output.setup,
                *length_setup,
                *declaration,
                IRExprStmt(expr=output.call),
            ]
        self._storage.validate_declaration_initializer(plan)
        if plan.initializer is not None:
            self._callable_boundaries.reject_local_declaration(
                node.type,
                plan.initializer,
                provenance,
            )
        initializer = None
        initializer_type = None
        initializer_owned = None
        initializer_before: tuple[IRStmt, ...] = ()
        initializer_after: tuple[IRStmt, ...] = ()
        if plan.initializer is not None:
            source_type = plan.source.type
            if source_type is not None and source_type.is_array:
                prepared_initializer = self._expressions.prepare_static_initializer(
                    plan.initializer,
                    source_type,
                    provenance,
                )
                initializer_before = prepared_initializer.before
                initializer = prepared_initializer.value
                initializer_after = prepared_initializer.after
            elif source_type is not None and source_type.is_static:
                initializer = self._expressions.lower_static_initializer(
                    plan.initializer,
                    provenance,
                )
            else:
                prepared = self._expressions.prepare_value(
                    plan.initializer,
                    plan.source.type,
                    provenance,
                )
                initializer_type = prepared.effective_type
                initializer_owned = prepared.owned
                initializer = self._types.upcast_class_pointer(
                    plan.source.type,
                    initializer_type,
                    prepared.value,
                )
        array_bound = (
            self._storage.materialize_array_bound(
                plan,
                self._expressions.lower_expr(
                    plan.array_size,
                    provenance,
                ),
            )
            if plan.array_size is not None
            else None
        )
        declaration = self._storage.materialize_declaration(
            plan,
            provenance,
            initializer=initializer,
            initializer_type=initializer_type,
            initializer_owned=initializer_owned,
            array_size=None if array_bound is None else array_bound.physical,
            logical_length=None if array_bound is None else array_bound.logical,
        )
        bound_setup = () if array_bound is None else array_bound.setup
        return [*initializer_before, *bound_setup, *declaration, *initializer_after]

    def lower_expression_statement(
        self,
        node: ExprStmt,
        provenance: CallableProvenance,
    ) -> list[IRStmt]:
        """Own statement-only expression traversal and discarded-result cleanup."""
        assertion = self.lower_assert_statement(
            node.expr,
            provenance,
        )
        if assertion is not None:
            return assertion
        destroy_receiver = self._mutex_destroy_receiver(node.expr)
        if destroy_receiver is not None:
            return self._ownership.materialize_release_target(
                self._expressions.lower_managed_slot_target(destroy_receiver, provenance)
            )
        result_type = self._session.type_of(node.expr)
        lowered = self._expressions.lower_expr(
            node.expr,
            provenance,
        )
        if self._is_fresh_thread_result(node.expr, result_type):
            temporary = IRVarDecl(
                c_type=CType(text=self._types.render(result_type)),
                name=self._session.fresh_temp("__btrc_discarded_thread"),
                init=lowered,
            )
            self._session.record_declaration(temporary)
            self._session.require_helper("__btrc_thread_free")
            return [
                temporary,
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_thread_free",
                        args=[IRVar(name=temporary.name)],
                        helper_ref="__btrc_thread_free",
                    )
                ),
            ]
        if self._values.is_managed(result_type) and self._ownership.lowered_result_is_owned(
            node.expr,
            provenance=provenance,
        ):
            return self._ownership.materialize_discarded_value(
                lowered,
                result_type,
            )
        return [IRExprStmt(expr=lowered)]

    def _mutex_destroy_receiver(self, expression):
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, FieldAccessExpr):
            return None
        if expression.callee.field != "destroy":
            return None
        receiver = expression.callee.obj
        return receiver if self._values.is_mutex(self._session.type_of(receiver)) else None

    def _is_fresh_thread_result(self, expression, result_type) -> bool:
        resolved = self._types.canonical_type(result_type)
        if resolved is None or resolved.base != "Thread":
            return False
        if isinstance(expression, (SpawnExpr, CallExpr)):
            return True
        if isinstance(expression, NullLiteral):
            return False
        if isinstance(expression, TernaryExpr):
            return self._is_fresh_thread_result(expression.true_expr, resolved) and self._is_fresh_thread_result(
                expression.false_expr, resolved
            )
        return False

    def lower_stmt(self, node, provenance: CallableProvenance) -> list[IRStmt]:
        """Lower a single AST statement to one or more IRStmts."""
        if isinstance(node, VarDeclStmt):
            return self.lower_declaration(
                node,
                provenance,
            )
        if isinstance(node, ReturnStmt):
            if self._gpu.gpu_cpu_item_return_active():
                value = (
                    self._expressions.lower_expr(
                        node.value,
                        provenance,
                    )
                    if node.value is not None
                    else None
                )
                return self._gpu.materialize_gpu_cpu_item_return(node, value)
            return self.lower_return(
                node,
                provenance,
            )
        if isinstance(node, IfStmt):
            return [
                self._lower_if(
                    node,
                    provenance,
                )
            ]
        if isinstance(node, WhileStmt):
            condition_reachability = provenance.condition_reachability(node.condition)
            condition_entry = provenance.snapshot()
            condition = self._expressions.lower_expr(
                node.condition,
                provenance,
            )
            condition_flow = provenance.snapshot()
            provenance.require_loop_edge_invariant(condition_entry, condition_flow, edge="condition")
            body, loop_flow = self._lower_loop_body(
                node.body,
                provenance,
            )
            provenance.complete_loop(
                loop_flow,
                condition_can_exit=condition_reachability.can_exit,
                condition_can_repeat=condition_reachability.can_repeat,
            )
            return [IRWhile(condition=condition, body=body)]
        if isinstance(node, DoWhileStmt):
            body, loop_flow = self._lower_loop_body(
                node.body,
                provenance,
            )
            if loop_flow.backedge_states:
                backedge_entry = provenance.merge_flows(*loop_flow.backedge_states)
                provenance.restore(backedge_entry)
                condition = self._expressions.lower_expr(
                    node.condition,
                    provenance,
                )
                condition_flow = provenance.snapshot()
                provenance.complete_do_while(
                    loop_flow,
                    condition_flow=condition_flow,
                    condition_reachability=provenance.condition_reachability(node.condition),
                )
            else:
                with provenance.isolated_flow():
                    condition = self._expressions.lower_expr(
                        node.condition,
                        provenance,
                    )
                provenance.complete_do_while(
                    loop_flow,
                    condition_flow=None,
                    condition_reachability=provenance.condition_reachability(node.condition),
                )
            return [IRDoWhile(body=body, condition=condition)]
        if isinstance(node, ForInStmt):
            return self._lower_for_in(node, provenance)
        if isinstance(node, CForStmt):
            with self._iteration.c_for_scope(node, provenance) as plan:
                if plan.initializer is not None:
                    plan.prefix.extend(
                        self.lower_declaration(
                            plan.initializer,
                            provenance,
                        )
                    )
                elif isinstance(node.init, ForInitExpr):
                    plan.init = IRExprStmt(
                        expr=self._expressions.lower_expr(
                            node.init.expression,
                            provenance,
                        )
                    )
                with self._iteration.c_for_condition_scope(plan, provenance):
                    plan.condition = (
                        self._expressions.lower_expr(
                            node.condition,
                            provenance,
                        )
                        if node.condition is not None
                        else IRLiteral(text="1")
                    )
                body, loop_flow = self._lower_loop_body(
                    node.body,
                    provenance,
                )
                if node.update is not None:
                    with self._iteration.c_for_update_scope(plan, loop_flow, provenance):
                        plan.update = self._expressions.lower_expr(
                            node.update,
                            provenance,
                        )
                return [self._iteration.materialize_c_for(plan, body, loop_flow, provenance)]
        if isinstance(node, ParallelForStmt):
            return self._lower_for_in(node, provenance)
        if isinstance(node, SwitchStmt):
            return [
                self._lower_switch(
                    node,
                    provenance,
                )
            ]
        if isinstance(node, BreakStmt):
            provenance.record_control_exit("break", self._session.control_context)
            try_pop = self._ownership.materialize_try_exit(self._ownership.exited_try_depth({"loop", "switch"}))
            return (
                self._lifetime.release_scope(self._ownership.get_control_managed_vars({"loop", "switch"}), force=True)
                + self._cleanup_scope.exit(self._cleanup_scope.control_marker({"loop", "switch"}))
                + try_pop
                + [IRBreak()]
            )
        if isinstance(node, ContinueStmt):
            provenance.record_control_exit("continue", self._session.control_context)
            try_pop = self._ownership.materialize_try_exit(self._ownership.exited_try_depth({"loop"}))
            return (
                self._lifetime.release_scope(self._ownership.get_control_managed_vars({"loop"}), force=True)
                + self._cleanup_scope.exit(self._cleanup_scope.control_marker({"loop"}))
                + try_pop
                + [IRContinue()]
            )
        if isinstance(node, ExprStmt):
            return self.lower_expression_statement(
                node,
                provenance,
            )
        if isinstance(node, DeleteStmt):
            return self._control_flow.lower_delete(
                node,
                provenance,
            )
        if isinstance(node, TryCatchStmt):
            return self._lower_try_catch(
                node,
                provenance,
            )
        if isinstance(node, ThrowStmt):
            return self._exceptions.lower_throw(
                node,
                provenance,
            )
        if isinstance(node, Block):
            return [self.lower_block(node, provenance)]
        if isinstance(node, KeepStmt):
            expr_type = self._session.type_of(node.expr)
            if not self._values.is_managed(expr_type) and self._session.type_of_is_specialized(node.expr):
                return []
            expr = self._expressions.lower_expr(
                node.expr,
                provenance,
            )
            edge_owner = self._session.persistent_edge_owner_c_name
            retained = (
                self._lifetime.retain_edge_value(expr, expr_type, IRVar(name=edge_owner))
                if edge_owner is not None
                else self._lifetime.retain_value(expr, expr_type)
            )
            return [IRExprStmt(expr=retained)]
        if isinstance(node, ReleaseStmt):
            target = self._expressions.lower_managed_slot_target(node.expr, provenance)
            edge_owner = self._persistent_collection_edge_owner(node.expr)
            if edge_owner is not None and target.edge_owner is None:
                target = replace(target, edge_owner=edge_owner)
            return self._ownership.materialize_release_target(target)
        raise self._expressions.unsupported_node("statement", node)

    def _persistent_collection_edge_owner(self, source) -> IRVar | None:
        owner = self._session.persistent_edge_owner_c_name
        if (
            owner is None
            or not isinstance(source, IndexExpr)
            or not isinstance(source.obj, FieldAccessExpr)
            or not isinstance(source.obj.obj, SelfExpr)
        ):
            return None
        return IRVar(name=owner)

    def _lower_try_catch(
        self,
        node: TryCatchStmt,
        provenance: CallableProvenance,
    ) -> list[IRStmt]:
        """Own recursive source traversal around an exception transaction."""
        with self._exceptions.try_catch_scope(node, provenance) as plan:
            with self._exceptions.try_body_scope(plan, provenance):
                plan.try_body = self.lower_block(
                    node.try_block,
                    provenance,
                )
            if not plan.finally_only:
                if node.catch_block is None:
                    raise CodegenError("try/catch transaction has no catch or finally block")
                with self._exceptions.catch_body_scope(plan, provenance) as catch_bindings:
                    plan.catch_body = self.lower_block(
                        node.catch_block,
                        provenance,
                        iteration_bindings=catch_bindings,
                    )
            self._exceptions.prepare_finally(plan, provenance)
            if node.finally_block is not None:
                with self._exceptions.finally_body_scope(plan, provenance):
                    plan.finally_body = self.lower_block(
                        node.finally_block,
                        provenance,
                    )
            return self._exceptions.materialize_try_catch(plan, provenance)

    def _lower_if(
        self,
        node: IfStmt,
        provenance: CallableProvenance,
    ):
        plan = self._control_flow.plan_conditional(
            node,
            provenance,
        )
        with self._control_flow.conditional_branch(provenance) as then_branch:
            then_branch.block = self.lower_block(
                node.then_block,
                provenance,
            )
        else_branch = None
        if isinstance(node.else_block, ElseBlock):
            with self._control_flow.conditional_branch(provenance) as else_branch:
                else_branch.block = self.lower_block(
                    node.else_block.body,
                    provenance,
                )
        elif isinstance(node.else_block, ElseIf):
            with self._control_flow.conditional_branch(provenance) as else_branch:
                else_branch.block = IRBlock(
                    stmts=[
                        self._lower_if(
                            node.else_block.if_stmt,
                            provenance,
                        )
                    ]
                )
        return self._control_flow.materialize_conditional(
            plan,
            then_branch,
            else_branch,
            provenance,
        )

    def _lower_switch(
        self,
        node: SwitchStmt,
        provenance: CallableProvenance,
    ):
        with self._control_flow.switch_scope(
            node,
            provenance,
        ) as plan:
            for source_case in node.cases:
                with self._control_flow.switch_case(
                    plan,
                    source_case,
                    provenance,
                ) as case:
                    for statement in source_case.body:
                        case.statements.extend(
                            self.lower_stmt(
                                statement,
                                provenance,
                            )
                        )
        assert plan.result is not None
        return plan.result

    def _lower_loop_body(
        self,
        body: Block | None,
        provenance: CallableProvenance,
        *,
        iteration_bindings=(),
        local_bindings=(),
    ):
        incoming = provenance.snapshot()
        capture = provenance.begin_loop_capture()
        self._ownership.push_loop_scope()
        self._ownership.push_control_context("loop")
        try:
            with provenance.isolated_flow() as body_isolation:
                lowered = self.lower_block(
                    body,
                    provenance,
                    iteration_bindings=iteration_bindings,
                    local_bindings=local_bindings,
                )
            assert body_isolation.outgoing is not None
            body_flow = body_isolation.outgoing
        finally:
            self._ownership.pop_control_context()
            self._ownership.pop_loop_scope()
            break_flows, continue_flows = provenance.finish_loop_capture(capture)
        backedge_flows = [*continue_flows]
        if IRStatementSequence(lowered.stmts).may_fall_through():
            backedge_flows.append(body_flow)
        return (
            lowered,
            CallableLoopFlow(head=incoming, break_states=tuple(break_flows), backedge_states=tuple(backedge_flows)),
        )

    def _lower_for_in(self, node, provenance: CallableProvenance) -> list[IRStmt]:
        """Lower one sequential or parallel for-in through a shared source plan."""
        is_range = self._iteration.is_range_loop(node)
        range_arguments = (
            [self._expressions.lower_expr(argument, provenance) for argument in node.iterable.args] if is_range else []
        )
        projection_storage = (
            self._expressions.prepare_projection_storage(node.iterable, provenance)
            if not is_range and self._iteration.is_fixed_array_iterable(node.iterable)
            else None
        )
        iterable = (
            None
            if is_range
            else (
                projection_storage.value
                if projection_storage is not None
                else self._expressions.lower_expr(node.iterable, provenance)
            )
        )
        with self._iteration.for_in_scope(
            node,
            iterable,
            range_arguments,
            provenance,
            projection_storage=projection_storage,
        ) as plan:
            body, loop_flow = self._lower_loop_body(
                plan.source_body,
                provenance,
                iteration_bindings=plan.bindings,
            )
            return self._iteration.materialize_for_in(plan, body, loop_flow, provenance)
