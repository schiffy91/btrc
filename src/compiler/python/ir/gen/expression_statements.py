"""Full-expression ARC cleanup for discarded source expressions."""

from __future__ import annotations

from ...ast_nodes import (
    CallExpr,
    ExprStmt,
    FieldAccessExpr,
    NullLiteral,
    SpawnExpr,
    TernaryExpr,
)
from ..nodes import CType, IRCall, IRCommaExpr, IRExprStmt, IRStmt, IRVar, IRVarDecl
from .expressions import lower_expr
from .ownership import owns_result
from .types import type_to_c


def lower_expression_statement(gen, node: ExprStmt) -> list[IRStmt]:
    """Lower one expression and release any discarded caller-owned result."""
    from .macro_boundaries import lower_assert_statement

    assertion = lower_assert_statement(
        node.expr,
        lower_condition=lambda condition: lower_expr(gen, condition),
        fresh_temp=gen.fresh_temp,
        record_decl=gen._func_var_decls.append,
        hosted=not gen.freestanding,
    )
    if assertion is not None:
        return assertion

    destroy_receiver = _mutex_destroy_receiver(gen, node.expr)
    if destroy_receiver is not None:
        from .arc import lower_release_expression

        return lower_release_expression(gen, destroy_receiver)
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
        statements.append(_release_owned_value(gen, value, result_type))
    else:
        statements = [IRExprStmt(expr=lowered)]

    return statements


def _release_owned_value(gen, target, value_type):
    """Build full-expression cleanup for one discarded owned value."""
    from .arc_ops import poll_release_batch
    from .managed_values import is_arc_type, release_value

    expressions = [release_value(gen, target, value_type)]
    flush = poll_release_batch(
        gen,
        types=[value_type] if is_arc_type(gen, value_type) else [],
    )
    if flush is not None:
        expressions.append(flush)
    return IRExprStmt(expr=IRCommaExpr(expressions=expressions))


def _mutex_destroy_receiver(gen, expression):
    if not isinstance(expression, CallExpr) or not isinstance(expression.callee, FieldAccessExpr):
        return None
    if expression.callee.field != "destroy":
        return None
    receiver = expression.callee.obj
    receiver_type = gen.analyzed.node_types.get(id(receiver))
    from .managed_values import is_mutex_type

    return receiver if is_mutex_type(gen, receiver_type) else None


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
