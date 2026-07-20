"""Conservative normal-completion queries for structured IR statements."""

from __future__ import annotations

import dataclasses

from .nodes import (
    IRBlock,
    IRBreak,
    IRContinue,
    IRIf,
    IRLiteral,
    IRReturn,
    IRVar,
)


def sequence_may_fall_through(statements) -> bool:
    """Whether control can reach the end of a statement sequence."""
    return all(statement_may_fall_through(statement) for statement in statements)


def statement_may_fall_through(statement) -> bool:
    if isinstance(statement, (IRReturn, IRBreak, IRContinue)):
        return False
    if isinstance(statement, IRBlock):
        return sequence_may_fall_through(statement.stmts)
    if isinstance(statement, IRIf) and statement.else_block is not None:
        return statement_may_fall_through(statement.then_block) or statement_may_fall_through(statement.else_block)
    return True


def sequence_references_variable(statements, name: str) -> bool:
    """Whether structured IR reads ``name`` anywhere in this sequence."""
    return any(_references_variable(statement, name) for statement in statements)


def _references_variable(value, name: str) -> bool:
    if isinstance(value, IRVar):
        return value.name == name
    if isinstance(value, IRLiteral):
        return False
    if isinstance(value, (list, tuple)):
        return any(_references_variable(item, name) for item in value)
    if not dataclasses.is_dataclass(value):
        return False
    return any(
        _references_variable(item, name)
        for field in dataclasses.fields(value)
        if not isinstance((item := getattr(value, field.name)), str)
    )


__all__ = [
    "sequence_may_fall_through",
    "sequence_references_variable",
    "statement_may_fall_through",
]
