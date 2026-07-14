"""Control-flow composition for nullable access-path facts."""

from ..ast_nodes import (
    Block,
    BreakStmt,
    ContinueStmt,
    ElseBlock,
    ElseIf,
    IfStmt,
    ReturnStmt,
    ThrowStmt,
)


class NullableControlFlowMixin:
    def _analyze_nullable_if(self, statement) -> None:
        self._analyze_expr(statement.condition)
        self._reject_thread_observation(statement.condition)
        continuing_flows = []
        then_flow = self._analyze_flow_branch(
            self._nonnull_facts_for_outcome(statement.condition, True),
            lambda: self._analyze_block(statement.then_block),
        )
        if not self._block_stops_fallthrough(statement.then_block):
            continuing_flows.append(then_flow)

        if isinstance(statement.else_block, ElseIf):
            else_flow = self._analyze_flow_branch(
                self._nonnull_facts_for_outcome(statement.condition, False),
                lambda: self._analyze_stmt(statement.else_block.if_stmt),
            )
            if not self._statement_stops_fallthrough(statement.else_block.if_stmt):
                continuing_flows.append(else_flow)
        elif isinstance(statement.else_block, ElseBlock):
            else_flow = self._analyze_flow_branch(
                self._nonnull_facts_for_outcome(statement.condition, False),
                lambda: self._analyze_block(statement.else_block.body),
            )
            if not self._block_stops_fallthrough(statement.else_block.body):
                continuing_flows.append(else_flow)
        else:
            continuing_flows.append(
                set(self._nonnull_paths)
                | self._nonnull_facts_for_outcome(
                    statement.condition,
                    False,
                )
            )
        self._nonnull_paths = self._join_nonnull_flows(continuing_flows)

    def _analyze_nullable_while(self, statement) -> None:
        self._analyze_expr(statement.condition)
        self._reject_thread_observation(statement.condition)
        self.loop_depth += 1
        self.break_depth += 1
        self._analyze_nullable_loop_body(
            statement.body,
            self._nonnull_facts_for_outcome(statement.condition, True),
        )
        self.loop_depth -= 1
        self.break_depth -= 1

    def _analyze_nullable_loop_body(self, body, facts=()) -> None:
        before_body = set(self._nonnull_paths)
        body_flow = self._analyze_flow_branch(
            facts,
            lambda: self._analyze_block(body),
        )
        # A loop body may execute zero times. Mutations in a possible
        # iteration can only remove facts known before the loop.
        self._nonnull_paths = before_body & body_flow

    def _block_stops_fallthrough(self, block) -> bool:
        if block is None:
            return False
        return any(self._statement_stops_fallthrough(statement) for statement in block.statements)

    def _statement_stops_fallthrough(self, statement) -> bool:
        if isinstance(
            statement,
            (ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt),
        ):
            return True
        if isinstance(statement, Block):
            return self._block_stops_fallthrough(statement)
        if not isinstance(statement, IfStmt):
            return False
        if not self._block_stops_fallthrough(statement.then_block):
            return False
        if isinstance(statement.else_block, ElseBlock):
            return self._block_stops_fallthrough(statement.else_block.body)
        if isinstance(statement.else_block, ElseIf):
            return self._statement_stops_fallthrough(statement.else_block.if_stmt)
        return False
