"""Loop-specific lexical visibility for the setjmp qualification pass."""

from ..nodes import IRAssign, IRExprStmt, IRVarDecl
from .setjmp_mutations import contains_setjmp, loop_mutated_names


def _statement_expressions(statement):
    if isinstance(statement, IRVarDecl):
        return (statement.array_size, statement.init)
    if isinstance(statement, IRAssign):
        return (statement.target, statement.value)
    if isinstance(statement, IRExprStmt):
        return (statement.expr,)
    return ()


class SetjmpLoopVisibilityMixin:
    def _for(self, statement, visible) -> None:
        if isinstance(statement.init, IRVarDecl):
            # All headers render before the `for` line. A condition/update
            # hoist can therefore precede a setjmp in the initializer.
            self._prepare_hoists(
                statement.init.array_size,
                visible,
                hoist_sink=visible,
            )
            self._prepare_hoists(
                statement.init.init,
                visible,
                hoist_sink=visible,
            )
        else:
            for expression in _statement_expressions(statement.init):
                self._prepare_hoists(expression, visible, hoist_sink=visible)
        self._prepare_hoists(statement.condition, visible, hoist_sink=visible)
        self._prepare_hoists(statement.update, visible, hoist_sink=visible)

        loop_visible = list(visible)
        if isinstance(statement.init, IRVarDecl):
            self._scan_expression(statement.init.array_size, visible)
            self._append_visible(loop_visible, statement.init)
            self._scan_expression(statement.init.init, loop_visible)
        else:
            for expression in _statement_expressions(statement.init):
                self._scan_expression(expression, loop_visible)
        if contains_setjmp(statement):
            self._mark_visible(
                loop_visible,
                loop_mutated_names(statement, effects=self._effects),
            )
        self._scan_expression(statement.condition, loop_visible)
        self._scan_expression(statement.update, loop_visible)
        self.block(statement.body, loop_visible)


__all__ = ["SetjmpLoopVisibilityMixin"]
