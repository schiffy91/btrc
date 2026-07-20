"""Structured statement boundaries for hosted C macros."""

from __future__ import annotations

from collections.abc import Callable

from ...ast_nodes import CallExpr, Identifier
from ..nodes import CType, IRCall, IRCast, IRExpr, IRExprStmt, IRStmt, IRVar, IRVarDecl


def lower_assert_statement(
    expression,
    *,
    lower_condition: Callable[[object], IRExpr],
    fresh_temp: Callable[[str], str],
    record_decl: Callable[[IRVarDecl], None],
    hosted: bool,
) -> list[IRStmt] | None:
    """Materialize a source ``assert`` argument before the C macro boundary.

    The C macro stringifies its argument, so a deeply lowered expression can
    exceed C11's required string-literal capacity even when formatted across
    physical lines.  Materialization also keeps btrc call semantics deliberate:
    the source argument is evaluated exactly once, including under ``NDEBUG``.
    """
    if not hosted or not _is_assert_call(expression):
        return None

    name = fresh_temp("__btrc_assert_condition")
    declaration = IRVarDecl(
        c_type=CType(text="bool"),
        name=name,
        init=lower_condition(expression.args[0]),
    )
    record_decl(declaration)
    value = IRVar(name=name)
    return [
        declaration,
        # C's NDEBUG assert expands away.  The explicit discard both documents
        # btrc's eager call semantics and keeps strict unused-variable builds
        # clean while the materialized initializer still runs.
        IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=value)),
        IRExprStmt(expr=IRCall(callee="assert", args=[value])),
    ]


def _is_assert_call(expression) -> bool:
    return (
        isinstance(expression, CallExpr)
        and isinstance(expression.callee, Identifier)
        and expression.callee.name == "assert"
        and len(expression.args) == 1
        and not any(expression.arg_names)
    )


__all__ = ["lower_assert_statement"]
