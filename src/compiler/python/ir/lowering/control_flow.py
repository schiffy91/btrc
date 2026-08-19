"""Cohesive control flow IR lowering owner."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.compiler.python.ir.nodes import IRBlock, IRCase, IRIf, IRStatementSequence, IRStmt, IRSwitch
from src.compiler.python.syntax.ast.generated import DeleteStmt, IfStmt, SwitchStmt

from .types import CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import (
        CallableFlowSnapshot,
        CallableProvenance,
        SwitchCallableCapture,
    )
    from .expressions import ExpressionLowerer
    from .ownership import CleanupScopeState, ManagedLifetimeLowerer, OwnershipLowerer
    from .session import LoweringSession


@dataclass(slots=True)
class ConditionalPlan:
    condition: object
    incoming: CallableFlowSnapshot


@dataclass(slots=True)
class ConditionalBranch:
    block: IRBlock | None = None
    flow: CallableFlowSnapshot | None = None


@dataclass(slots=True)
class SwitchPlan:
    source: SwitchStmt
    value: object
    incoming: CallableFlowSnapshot
    capture: SwitchCallableCapture
    cases: list[IRCase] = field(default_factory=list)
    fallthrough_flow: CallableFlowSnapshot | None = None
    result: IRSwitch | None = None


@dataclass(slots=True)
class SwitchCasePlan:
    value: object
    statements: list[IRStmt] = field(default_factory=list)


class ControlFlowLowerer:
    """Own control flow lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        expressions: ExpressionLowerer,
        ownership: OwnershipLowerer,
        lifetime: ManagedLifetimeLowerer,
        cleanup_scope: CleanupScopeState,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._expressions = expressions
        self._ownership = ownership
        self._lifetime = lifetime
        self._cleanup_scope = cleanup_scope

    def plan_conditional(
        self,
        node: IfStmt,
        provenance: CallableProvenance,
    ) -> ConditionalPlan:
        return ConditionalPlan(
            condition=self._lower_expr(
                node.condition,
                provenance,
            ),
            incoming=provenance.snapshot(),
        )

    @contextmanager
    def conditional_branch(self, provenance: CallableProvenance) -> Iterator[ConditionalBranch]:
        branch = ConditionalBranch()
        with provenance.isolated_flow() as isolation:
            yield branch
        assert isolation.outgoing is not None
        branch.flow = isolation.outgoing

    def materialize_conditional(
        self,
        plan: ConditionalPlan,
        then_branch: ConditionalBranch,
        else_branch: ConditionalBranch | None,
        provenance: CallableProvenance,
    ) -> IRIf:
        assert then_branch.block is not None and then_branch.flow is not None
        exit_flows = []
        if IRStatementSequence(then_branch.block.stmts).may_fall_through():
            exit_flows.append(then_branch.flow)
        if else_branch is None:
            exit_flows.append(plan.incoming)
            else_block = None
        else:
            assert else_branch.block is not None and else_branch.flow is not None
            else_block = else_branch.block
            if IRStatementSequence(else_block.stmts).may_fall_through():
                exit_flows.append(else_branch.flow)
        if exit_flows:
            provenance.join_flows(*exit_flows)
        else:
            provenance.restore(plan.incoming)
        return IRIf(
            condition=plan.condition,
            then_block=then_branch.block,
            else_block=else_block,
        )

    @contextmanager
    def switch_scope(
        self,
        node: SwitchStmt,
        provenance: CallableProvenance,
    ) -> Iterator[SwitchPlan]:
        plan = SwitchPlan(
            source=node,
            value=self._lower_expr(
                node.value,
                provenance,
            ),
            incoming=provenance.snapshot(),
            capture=provenance.begin_switch_capture(),
        )
        self._ownership.push_control_context("switch")
        try:
            yield plan
        finally:
            self._ownership.pop_control_context()
            break_flows = provenance.finish_switch_capture(plan.capture)
        exit_flows = [*break_flows]
        if plan.fallthrough_flow is not None:
            exit_flows.append(plan.fallthrough_flow)
        if not any(case.value is None for case in node.cases):
            exit_flows.append(plan.incoming)
        if exit_flows:
            provenance.join_flows(*exit_flows)
        else:
            provenance.restore(plan.incoming)
        plan.result = IRSwitch(
            value=plan.value,
            cases=plan.cases,
            can_fall_through=bool(exit_flows),
        )

    @contextmanager
    def switch_case(
        self,
        plan: SwitchPlan,
        source_case,
        provenance: CallableProvenance,
    ) -> Iterator[SwitchCasePlan]:
        value = (
            self._lower_expr(
                source_case.value,
                provenance,
            )
            if source_case.value
            else None
        )
        provenance.restore(plan.incoming)
        if plan.fallthrough_flow is not None:
            provenance.join_flows(plan.incoming, plan.fallthrough_flow)
        case = SwitchCasePlan(value=value)
        lowered_case = None
        falls_through = False
        with provenance.isolated_flow() as isolation:
            enclosing = provenance.begin_scope()
            marker = self._cleanup_scope.push()
            self._ownership.push_managed_scope()
            self._ownership.push_local_ownership_scope()
            self._session.c_array_scopes.append({})
            managed_scope_active = True
            try:
                yield case
                sequence = IRStatementSequence(case.statements)
                falls_through = sequence.may_fall_through()
                managed = self._ownership.pop_managed_scope()
                managed_scope_active = False
                marker_active = self._cleanup_scope.is_active(marker)
                marker_referenced = falls_through or sequence.references_variable(marker or "")
                if marker_active and marker_referenced:
                    case.statements[:0] = self._cleanup_scope.entry(marker)
                if falls_through:
                    case.statements.extend(self._lifetime.release_scope(managed))
                    if marker_active and marker_referenced:
                        case.statements.extend(self._cleanup_scope.exit(marker))
                lowered_case = IRCase(
                    value=value,
                    body=case.statements,
                    falls_through=falls_through,
                )
            finally:
                if managed_scope_active:
                    self._ownership.pop_managed_scope()
                self._session.c_array_scopes.pop()
                self._ownership.pop_local_ownership_scope()
                self._cleanup_scope.pop()
                provenance.finish_scope(enclosing)
        assert isolation.outgoing is not None and lowered_case is not None
        plan.cases.append(lowered_case)
        plan.fallthrough_flow = isolation.outgoing if falls_through else None

    def lower_delete(self, node: DeleteStmt, provenance: CallableProvenance) -> list[IRStmt]:
        """Lower delete through the shared take-clear destruction boundary."""
        self._ownership.mark_borrowed_cycle_seeds()
        plan = self._ownership.plan_release(node.expr)
        return self._ownership.materialize_release(
            plan,
            self._expressions.lower_expr(
                node.expr,
                provenance,
            ),
        )

    def _lower_expr(self, node, provenance: CallableProvenance):
        """Convenience wrapper to avoid circular import at module level."""
        return self._expressions.lower_expr(
            node,
            provenance,
        )
