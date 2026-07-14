"""Full-expression ARC cleanup for discarded source expressions."""

from __future__ import annotations

from ...ast_nodes import (
    CallExpr,
    ExprStmt,
    NullLiteral,
    SpawnExpr,
    TernaryExpr,
)
from ..nodes import CType, IRCall, IRExprStmt, IRStmt, IRVar, IRVarDecl
from .arguments_arc import _release_stmt
from .expressions import lower_expr
from .ownership import owns_result
from .types import type_to_c


def lower_expression_statement(gen, node: ExprStmt) -> list[IRStmt]:
    """Lower one expression and release any discarded caller-owned result."""
    lowered = lower_expr(gen, node.expr)

    result_type = gen.analyzed.node_types.get(id(node.expr))
    from .managed_values import is_managed_type

    if _is_fresh_thread_result(gen, node.expr, result_type):
        temporary = IRVarDecl(
            c_type=CType(text=type_to_c(result_type)),
            name=gen.fresh_temp("__btrc_discarded_thread"),
            init=lowered,
        )
        gen._func_var_decls.append(temporary)
        gen.use_helper("__btrc_thread_free")
        statements = [
            temporary,
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_thread_free",
                    args=[IRVar(name=temporary.name)],
                    helper_ref="__btrc_thread_free",
                )
            ),
        ]
    elif owns_result(gen, node.expr) and is_managed_type(gen, result_type):
        temporary = IRVarDecl(
            c_type=CType(text=type_to_c(result_type)),
            name=gen.fresh_temp("__btrc_discarded"),
            init=lowered,
        )
        gen._func_var_decls.append(temporary)
        value = IRVar(name=temporary.name)
        statements = [temporary]
        statements.append(_release_stmt(gen, value, result_type))
    else:
        statements = [IRExprStmt(expr=lowered)]

    return statements


def _is_fresh_thread_result(gen, expression, result_type) -> bool:
    from .type_resolution import canonical_type

    resolved_type = canonical_type(
        result_type,
        gen.analyzed.typedef_table,
    )
    if resolved_type is None or resolved_type.base != "Thread":
        return False
    if isinstance(expression, (SpawnExpr, CallExpr)):
        return True
    if isinstance(expression, NullLiteral):
        return False
    if isinstance(expression, TernaryExpr):
        return _is_fresh_thread_result(
            gen,
            expression.true_expr,
            resolved_type,
        ) and _is_fresh_thread_result(
            gen,
            expression.false_expr,
            resolved_type,
        )
    return False


__all__ = ["lower_expression_statement"]
