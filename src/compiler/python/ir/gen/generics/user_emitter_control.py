"""Control-flow statement lowering for monomorphized generic methods."""

from __future__ import annotations

from ...nodes import (
    IRBlock,
    IRCase,
    IRDoWhile,
    IRIf,
    IRSwitch,
    IRWhile,
)
from .user_emitter_exceptions import _UserGenericExceptionMixin
from .user_emitter_scopes import (
    emit_scoped_stmts,
    pop_control_context,
    push_control_context,
)


class _UserGenericControlMixin(_UserGenericExceptionMixin):
    def _loop_stmts(self, statements, *, iteration_bindings=(), may_skip=True):
        from ...completion import StatementSequence
        from ..callable_loop_flow import (
            begin_callable_loop_capture,
            finish_callable_loop_capture,
        )
        from .user_callable_provenance import (
            join_callable_flows,
            lower_isolated_callable_flow,
            restore_callable_flow,
            snapshot_callable_flow,
        )

        incoming = snapshot_callable_flow(self)
        capture = begin_callable_loop_capture(self)
        push_control_context(self, "loop")
        try:
            lowered, body_flow = lower_isolated_callable_flow(
                self,
                lambda: emit_scoped_stmts(
                    self,
                    statements,
                    iteration_bindings=iteration_bindings,
                ),
            )
        finally:
            pop_control_context(self)
            break_flows, continue_flows = finish_callable_loop_capture(
                self,
                capture,
            )
        exit_flows = [*break_flows, *continue_flows]
        if StatementSequence(lowered).may_fall_through():
            exit_flows.append(body_flow)
        if may_skip:
            exit_flows.append(incoming)
        if exit_flows:
            join_callable_flows(self, *exit_flows)
        else:
            restore_callable_flow(self, incoming)
        return lowered

    def _if_stmt(self, s) -> IRIf:
        from ....ast_nodes import Block, ElseBlock, ElseIf
        from .user_callable_provenance import (
            join_callable_flows,
            lower_isolated_callable_flow,
            snapshot_callable_flow,
        )

        cond = self._expr(s.condition)
        incoming = snapshot_callable_flow(self)
        then_stmts, then_flow = lower_isolated_callable_flow(
            self,
            lambda: self.emit_stmts(s.then_block.statements) if s.then_block else [],
        )
        then_block = IRBlock(stmts=then_stmts)

        else_block = None
        else_flow = incoming
        if s.else_block:
            eb = s.else_block
            if isinstance(eb, ElseBlock):
                eb = eb.body
            if isinstance(eb, Block):
                else_stmts, else_flow = lower_isolated_callable_flow(
                    self,
                    lambda: self.emit_stmts(eb.statements),
                )
                else_block = IRBlock(stmts=else_stmts)
            elif isinstance(eb, ElseIf):
                inner, else_flow = lower_isolated_callable_flow(
                    self,
                    lambda: self._if_stmt(eb.if_stmt),
                )
                else_block = IRBlock(stmts=[inner])

        join_callable_flows(self, then_flow, else_flow)
        return IRIf(condition=cond, then_block=then_block, else_block=else_block)

    def _cfor_stmt(self, statement):
        from .user_emitter_loops import lower_generic_cfor

        return lower_generic_cfor(self, statement)

    def _forin_stmt(self, s) -> list:
        from ....ast_nodes import CallExpr, Identifier

        if (
            isinstance(s.iterable, CallExpr)
            and isinstance(s.iterable.callee, Identifier)
            and s.iterable.callee.name == "range"
        ):
            return self._range_forin_stmt(s)
        return self._iterable_forin_stmt(s)

    def _range_forin_stmt(self, statement) -> list:
        from .user_emitter_loops import lower_generic_range_forin

        return lower_generic_range_forin(self, statement)

    def _iterable_forin_stmt(self, s) -> list:
        from .user_emitter_iteration_protocol import (
            lower_iterable_forin,
        )

        return lower_iterable_forin(self, s)

    def _string_forin_stmt(self, statement) -> list:
        from .user_emitter_iteration_protocol import lower_string_forin

        return lower_string_forin(self, statement)

    def _while_stmt(self, s) -> IRWhile:
        condition = self._expr(s.condition)
        body_stmts = self._loop_stmts(s.body.statements)
        return IRWhile(condition=condition, body=IRBlock(stmts=body_stmts))

    def _dowhile_stmt(self, s) -> IRDoWhile:
        body_stmts = self._loop_stmts(
            s.body.statements,
            may_skip=False,
        )
        return IRDoWhile(body=IRBlock(stmts=body_stmts), condition=self._expr(s.condition))

    def _switch_stmt(self, statement) -> IRSwitch:
        from ...completion import StatementSequence
        from .user_callable_provenance import (
            join_callable_flows,
            lower_isolated_callable_flow,
            restore_callable_flow,
            snapshot_callable_flow,
        )

        switch_value = self._expr(statement.value)
        incoming = snapshot_callable_flow(self)
        cases = []
        case_flows = []
        fallthrough_flow = None
        push_control_context(self, "switch")
        try:
            for clause in statement.cases:
                case_value = self._expr(clause.value) if clause.value else None
                restore_callable_flow(self, incoming)
                if fallthrough_flow is not None:
                    join_callable_flows(self, incoming, fallthrough_flow)

                def lower_case(case=clause):
                    body = self.emit_stmts(case.body)
                    return body, StatementSequence(body).may_fall_through()

                lowered, case_flow = lower_isolated_callable_flow(
                    self,
                    lower_case,
                )
                body, falls_through = lowered
                cases.append(
                    IRCase(
                        value=case_value,
                        body=body,
                        falls_through=falls_through,
                    )
                )
                case_flows.append(case_flow)
                fallthrough_flow = case_flow if falls_through else None
        finally:
            pop_control_context(self)
        if not any(clause.value is None for clause in statement.cases):
            case_flows.append(incoming)
        join_callable_flows(self, *case_flows)
        return IRSwitch(value=switch_value, cases=cases)
