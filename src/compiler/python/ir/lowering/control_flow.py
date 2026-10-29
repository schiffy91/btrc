"""Cohesive control flow IR lowering owner."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.flow import JumpScopeIndex
from src.compiler.python.ir.nodes import (
    IRBlock,
    IRCase,
    IRGoto,
    IRIf,
    IRLabel,
    IRLineMarker,
    IRStatementSequence,
    IRStmt,
    IRSwitch,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import DeleteStmt, GotoStmt, IfStmt, LabelStmt, SwitchStmt, VarDeclStmt

from .types import CodegenError, CTypeLowerer

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


@dataclass(slots=True)
class LoweredLabel:
    owner_prefix: int
    declared: frozenset[str]
    entry: CallableFlowSnapshot
    ir_index: int


@dataclass(slots=True)
class JumpLoweringFrame:
    source: object
    managed_position: int
    marker_position: int
    marker: str | None
    try_depth: int
    callable_depth: int
    statements: list[IRStmt]
    statement_start: int = 0
    statement_ir_start: int = 0
    labels: dict[str, LoweredLabel] = field(default_factory=dict)
    pending: dict[str, list[CallableFlowSnapshot]] = field(default_factory=dict)
    forward: list[tuple[str, int]] = field(default_factory=list)


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

    @contextmanager
    def jump_frame(self, source, statements: list[IRStmt], provenance: CallableProvenance, marker):
        previous_index = self._session.jump_index
        previous_vlas = self._session.variable_length_declarations
        root = id(source) in self._analyzed.jump_body_ids
        if root:
            self._session.jump_index = JumpScopeIndex.build(source)
            self._session.variable_length_declarations = set()
        index = self._session.jump_index
        if index is None or id(source) not in index.lists:
            yield
            return
        frame = JumpLoweringFrame(
            source,
            self._ownership.managed_scope_depth - 1,
            self._cleanup_scope.depth - 1,
            marker,
            self._session.in_trycatch_depth,
            provenance.scope_depth,
            statements,
        )
        self._session.jump_frames.append(frame)
        try:
            yield
            self._validate_forward_entries(frame)
        finally:
            self._session.jump_frames.pop()
            if root:
                self._session.jump_index = previous_index
                self._session.variable_length_declarations = previous_vlas

    @contextmanager
    def jump_statement(self, source):
        frames = self._session.jump_frames
        if not frames:
            yield
            return
        frame = frames[-1]
        frame.statement_start = len(self._ownership.managed_scope(frame.managed_position))
        frame.statement_ir_start = len(frame.statements)
        yield
        difference = len(self._ownership.managed_scope(frame.managed_position)) - frame.statement_start
        if difference < 0 or difference > int(isinstance(source, VarDeclStmt)):
            raise CodegenError("statement lowering left a managed owner registered in its enclosing scope")

    def lower_goto(self, source: GotoStmt, provenance: CallableProvenance) -> list[IRStmt]:
        index = self._session.jump_index
        target = index.target(source) if index is not None else None
        frame = next(
            (
                frame
                for frame in reversed(self._session.jump_frames)
                if target is not None and frame.source is target.path[-1][0].node
            ),
            None,
        )
        if frame is None or index is None:
            raise CodegenError("goto target has no active lowering frame")
        if frame.try_depth != self._session.in_trycatch_depth:
            raise CodegenError("goto crosses an exception region during lowering")
        backward = index.is_backward(source)
        label = frame.labels.get(source.name)
        if backward and label is None:
            raise CodegenError("backward goto target has not been lowered")
        prefix = label.owner_prefix if backward else frame.statement_start
        incoming = provenance.project_goto(
            frame.callable_depth,
            declared=label.declared if backward else None,
            entered={declaration.name for declaration in index.entered_declarations(source)} if not backward else set(),
        )
        if backward:
            provenance.require_goto_back_edge(source.name, label.entry, incoming)
        else:
            frame.pending.setdefault(source.name, []).append(incoming)
            frame.forward.append((source.name, frame.statement_ir_start))
        statements = self._lifetime.release_scope(
            self._ownership.jump_owners(frame.managed_position, prefix), force=True
        )
        marker = self._cleanup_scope.marker_from(frame.marker_position + (0 if backward else 1))
        statements.extend(self._cleanup_scope.exit(marker))
        if backward and marker is not None and marker == frame.marker:
            for owner in self._ownership.managed_scope(frame.managed_position)[:prefix]:
                if owner.cleanup_registration is None:
                    raise CodegenError("backward goto preserves an owner without a cleanup registration")
                statements.extend(self._lifetime.reissue_cleanup(owner.cleanup_registration))
        statements.append(IRGoto(name=provenance.source_binding_c_name(source.name)))
        return statements

    def lower_label(self, source: LabelStmt, provenance: CallableProvenance) -> list[IRStmt]:
        index = self._session.jump_index
        if index is None:
            raise CodegenError("label has no active jump index")
        if not index.targeted(source.name):
            return []
        frame = self._session.jump_frames[-1]
        entry = provenance.enter_label(
            frame.pending.pop(source.name, []), falls_in=IRStatementSequence(frame.statements).may_fall_through()
        )
        frame.labels[source.name] = LoweredLabel(
            len(self._ownership.managed_scope(frame.managed_position)),
            provenance.declared_names(frame.callable_depth),
            entry,
            len(frame.statements),
        )
        return [IRLabel(name=provenance.source_binding_c_name(source.name))]

    def _validate_forward_entries(self, frame: JumpLoweringFrame) -> None:
        owners = {owner.c_name or owner.name for owner in self._ownership.managed_scope(frame.managed_position)}
        for name, start in frame.forward:
            label = frame.labels.get(name)
            if label is None:
                raise CodegenError("forward goto target has not been lowered")
            suffix = IRStatementSequence(frame.statements[label.ir_index :])
            for statement in frame.statements[start : label.ir_index]:
                if not isinstance(statement, IRVarDecl):
                    continue
                if id(statement) in self._session.variable_length_declarations:
                    raise CodegenError("goto enters variable-length storage during lowering")
                if statement.is_static or statement.is_extern:
                    continue
                if statement.name in owners or suffix.references_variable(statement.name):
                    raise CodegenError("goto bypasses live automatic storage during lowering")

    @classmethod
    def mark_tail_labels(cls, statements: list[IRStmt]) -> None:
        tail = [statement for statement in statements if not isinstance(statement, IRLineMarker)]
        if not tail:
            return
        last = tail[-1]
        if isinstance(last, IRLabel):
            while tail and isinstance(tail[-1], IRLabel):
                last = tail.pop()
            last.falls_through = True
        elif isinstance(last, IRBlock):
            cls.mark_tail_labels(last.stmts)
        elif isinstance(last, IRIf):
            cls.mark_tail_labels(last.then_block.stmts)
            if last.else_block is not None:
                cls.mark_tail_labels(last.else_block.stmts)

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
                with self.jump_frame(source_case, case.statements, provenance, marker):
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
                    self.mark_tail_labels(case.statements)
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
        return self._ownership.materialize_delete_target(
            self._expressions.lower_managed_slot_target(node.expr, provenance)
        )

    def _lower_expr(self, node, provenance: CallableProvenance):
        """Convenience wrapper to avoid circular import at module level."""
        return self._expressions.lower_expr(
            node,
            provenance,
        )
