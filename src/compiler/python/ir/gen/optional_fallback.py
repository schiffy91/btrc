"""Structured fallback replacement for optional-chain value IR."""

from __future__ import annotations

from dataclasses import replace

from ..nodes import (
    IRBinOp,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRStmtExpr,
    IRTernary,
    IRVar,
)


def replace_optional_fallback(
    left: IRExpr,
    fallback: IRExpr,
) -> IRExpr | None:
    """Fuse ``??`` into an optional chain's value-producing path.

    Ownership sequencing can wrap an optional projection in one or more
    statement expressions. Follow the final value back through its defining
    assignment instead of assuming the optional ternary is the outermost node.
    """
    return _replace_value_fallback(left, fallback)


def _replace_value_fallback(expr: IRExpr, fallback: IRExpr) -> IRExpr | None:
    if isinstance(expr, IRTernary):
        return replace(expr, false_expr=fallback)
    if isinstance(expr, IRStmtExpr):
        result = _replace_value_fallback(expr.result, fallback)
        return replace(expr, result=result) if result is not None else None
    if isinstance(expr, IRCommaExpr) and expr.expressions:
        expressions = list(expr.expressions)
        rewritten = _replace_value_fallback(expressions[-1], fallback)
        if rewritten is not None:
            expressions[-1] = rewritten
            return replace(expr, expressions=expressions)
        result_name = _result_var_name(expressions[-1])
        if result_name is None:
            return None
        for index in range(len(expressions) - 2, -1, -1):
            definition = expressions[index]
            if not _assigns_var(definition, result_name):
                continue
            rewritten = _replace_value_fallback(definition.right, fallback)
            if rewritten is None:
                return None
            expressions[index] = replace(definition, right=rewritten)
            return replace(expr, expressions=expressions)
        return None
    if isinstance(expr, IRBinOp) and expr.op == "=":
        right = _replace_value_fallback(expr.right, fallback)
        return replace(expr, right=right) if right is not None else None
    if isinstance(expr, IRCast):
        inner = _replace_value_fallback(expr.expr, fallback)
        return replace(expr, expr=inner) if inner is not None else None
    return None


def _result_var_name(expr: IRExpr) -> str | None:
    return expr.name if isinstance(expr, IRVar) else None


def _assigns_var(expr: IRExpr, name: str) -> bool:
    return bool(
        isinstance(expr, IRBinOp) and expr.op == "=" and isinstance(expr.left, IRVar) and expr.left.name == name
    )


__all__ = ["replace_optional_fallback"]
