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
from .types import CTypeRenderer


def lower_expression_statement(
    gen,
    node: ExprStmt,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> list[IRStmt]:
    """Lower one expression and release any discarded caller-owned result."""
    from .macro_boundaries import lower_assert_statement

    assertion = lower_assert_statement(
        node.expr,
        lower_condition=lambda condition: lower_expr(
            gen,
            condition,
            type_renderer,
            default_arguments,
        ),
        fresh_temp=gen.fresh_temp,
        record_decl=gen.context.function_declarations.append,
        hosted=not gen.freestanding and "assert" not in gen.analyzed.function_table,
    )
    if assertion is not None:
        return assertion

    destroy_receiver = _mutex_destroy_receiver(gen, node.expr)
    if destroy_receiver is not None:
        return gen.managed_releases.lower_expression(
            gen,
            destroy_receiver,
        )
    lowered = lower_expr(
        gen,
        node.expr,
        type_renderer,
        default_arguments,
    )

    from .assignments import _is_gpu_output_assignment

    if _is_gpu_output_assignment(gen, node.expr):
        return [IRExprStmt(expr=lowered)]

    result_type = gen.analyzed.node_types.get(id(node.expr))

    if _is_fresh_thread_result(gen, node.expr, result_type):
        temporary = IRVarDecl(
            c_type=CType(text=type_renderer.render(result_type)),
            name=gen.fresh_temp("__btrc_discarded_thread"),
            init=lowered,
        )
        gen.context.function_declarations.append(temporary)
        gen.helpers.use("__btrc_thread_free")
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
    elif gen.ownership.owns_result(node.expr) and gen.managed_values.is_managed(result_type):
        temporary = IRVarDecl(
            c_type=CType(text=type_renderer.render(result_type)),
            name=gen.fresh_temp("__btrc_discarded"),
            init=lowered,
        )
        gen.context.function_declarations.append(temporary)
        value = IRVar(name=temporary.name)
        statements = [temporary]
        statements.append(_release_owned_value(gen, value, result_type))
    else:
        statements = [IRExprStmt(expr=lowered)]

    return statements


def _release_owned_value(gen, target, value_type):
    """Build full-expression cleanup for one discarded owned value."""
    expressions = [gen.lifetime.release_value(target, value_type)]
    flush = gen.lifetime.poll_release_batch(
        types=[value_type] if gen.managed_values.is_arc(value_type) else [],
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

    return receiver if gen.managed_values.is_mutex(receiver_type) else None


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
