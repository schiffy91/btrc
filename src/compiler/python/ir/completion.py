"""Conservative control-flow facts for a structured IR statement sequence."""

from __future__ import annotations

from .expr_nodes import IRVar
from .nodes import (
    IRBlock,
    IRBreak,
    IRContinue,
    IRIf,
    IRReturn,
)
from .optimizer_walk import IRTree


class StatementSequence:
    """A structured statement sequence and its conservative flow facts."""

    def __init__(self, statements):
        self._statements = statements

    def may_fall_through(self) -> bool:
        """Whether control can reach the end of this sequence."""

        return all(self._statement_may_fall_through(statement) for statement in self._statements)

    def references_variable(self, name: str) -> bool:
        """Whether structured IR reads ``name`` anywhere in this sequence."""

        return any(isinstance(node, IRVar) and node.name == name for node in IRTree(self._statements))

    @classmethod
    def _statement_may_fall_through(cls, statement) -> bool:
        if isinstance(statement, (IRReturn, IRBreak, IRContinue)):
            return False
        if isinstance(statement, IRBlock):
            return cls(statement.stmts).may_fall_through()
        if isinstance(statement, IRIf) and statement.else_block is not None:
            return cls._statement_may_fall_through(statement.then_block) or cls._statement_may_fall_through(
                statement.else_block
            )
        return True


__all__ = ["StatementSequence"]
