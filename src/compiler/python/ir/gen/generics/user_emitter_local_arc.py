"""ARC replacement for owned locals in monomorphized generic methods."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRCommaExpr,
    IRExprStmt,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from ..managed_values import (
    poll_released_values,
    release_value,
    retain_value,
)
from .user_emitter_scopes import managed_local_type


def lower_generic_local_assignment(emitter, expression):
    """Replace an owned local without leaking its old reference."""
    from ....ast_nodes import Identifier

    if (
        expression.op != "="
        or not isinstance(expression.target, Identifier)
        or managed_local_type(emitter, expression.target.name) is None
    ):
        return None
    target_type = emitter._resolve_expr_type(expression.target)
    if not emitter._is_managed_type(target_type):
        return None

    value = emitter._assignment_value(target_type, expression.value)
    value_type = emitter._resolve_expr_type(expression.value)
    if emitter._gen:
        from ..upcast import upcast_class_pointer

        value = upcast_class_pointer(
            emitter._gen,
            target_type,
            value_type,
            value,
        )

    new_decl = _temporary(emitter, "__btrc_local_new", target_type)
    old_decl = _temporary(emitter, "__btrc_local_old", target_type)
    new_value = IRVar(name=new_decl.name)
    old_value = IRVar(name=old_decl.name)
    target = IRVar(name=expression.target.name)
    sequence = [
        IRBinOp(left=new_value, op="=", right=value),
        IRBinOp(left=old_value, op="=", right=target),
    ]
    if not emitter._owns_expr(expression.value):
        sequence.append(retain_value(emitter._gen, new_value, target_type))
    sequence.extend(
        [
            release_value(emitter._gen, old_value, target_type),
            IRBinOp(left=target, op="=", right=new_value),
        ]
    )
    flush = poll_released_values(emitter._gen, target_type)
    if flush is not None:
        sequence.append(flush)
    sequence.append(target)
    return IRStmtExpr(
        stmts=[new_decl, old_decl],
        result=IRCommaExpr(expressions=sequence),
    )


def lower_generic_expression_statement(emitter, expression):
    """Consume a discarded caller-owned result at the statement boundary."""
    result_type = emitter._resolve_expr_type(expression)
    value = emitter._expr(expression)
    if not emitter._is_managed_type(result_type) or not emitter._owns_expr(expression):
        return [IRExprStmt(expr=value)]
    temporary = _temporary(emitter, "__btrc_discarded", result_type)
    temporary.init = value
    statements = [
        temporary,
        IRExprStmt(expr=release_value(emitter._gen, IRVar(name=temporary.name), result_type)),
    ]
    flush = poll_released_values(emitter._gen, result_type)
    if flush is not None:
        statements.append(IRExprStmt(expr=flush))
    return statements


def _temporary(emitter, prefix: str, type_expr) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=emitter.iter_value_c(type_expr)),
        name=emitter._fresh_temp(prefix),
    )
    emitter._func_var_decls.append(declaration)
    return declaration


__all__ = [
    "lower_generic_expression_statement",
    "lower_generic_local_assignment",
]
