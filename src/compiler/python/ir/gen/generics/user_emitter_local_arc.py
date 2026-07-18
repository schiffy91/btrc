"""ARC replacement for owned locals in monomorphized generic methods."""

from __future__ import annotations

from ...nodes import CType, IRBinOp, IRExprStmt, IRVar, IRVarDecl
from ..managed_values import poll_released_values, release_value
from .user_emitter_scopes import managed_local_type


def lower_generic_local_assignment(emitter, expression):
    """Replace an owned local without leaking its old reference."""
    from ....ast_nodes import Identifier

    if not isinstance(expression.target, Identifier) or managed_local_type(emitter, expression.target.name) is None:
        return None
    target_type = emitter._resolve_expr_type(expression.target)
    from ..managed_values import managed_local_value_type

    target_type = managed_local_value_type(
        target_type,
        managed_local_type(emitter, expression.target.name),
    )
    if not emitter._is_managed_type(target_type):
        return None

    target = IRVar(name=expression.target.name)
    return lower_generic_managed_slot_assignment(
        emitter,
        expression,
        target,
        target_type,
    )


def lower_generic_managed_slot_assignment(
    emitter,
    expression,
    target,
    target_type,
):
    """Replace or compound-update one persistent managed slot."""
    if expression.op != "=":
        return _lower_generic_local_compound(
            emitter,
            expression,
            target,
            target_type,
        )
    value = emitter._assignment_value(target_type, expression.value)
    from ..prepared_values import prepare_generic_value

    prepared = prepare_generic_value(
        emitter,
        expression.value,
        target_type,
        lowered=value,
    )
    value = prepared.value
    value_type = prepared.effective_type
    from ..upcast import upcast_class_pointer

    value = upcast_class_pointer(
        emitter._gen,
        target_type,
        value_type,
        value,
    )
    from ..managed_replacement import lower_managed_slot_replacement

    return lower_managed_slot_replacement(
        emitter._gen,
        target=target,
        target_type=target_type,
        value=value,
        value_owned=prepared.owned,
        c_type=emitter.iter_value_c,
        fresh_temp=emitter._fresh_temp,
        record_decl=emitter._func_var_decls.append,
        cleanup_active=emitter._exception_cleanup_active(),
        activate_cleanup=emitter._activate_cleanup_registration,
    )


def _lower_generic_local_compound(emitter, expression, target, target_type):
    from ..managed_compound import (
        lower_managed_compound_operator,
        managed_compound_keeps_rhs,
    )
    from ..managed_updates import lower_managed_compound_update

    right_type = emitter._resolve_expr_type(expression.value) or target_type
    return lower_managed_compound_update(
        emitter._gen,
        value_type=target_type,
        right_type=right_type,
        old_expr=target,
        current_expr=target,
        right_expr=emitter._assignment_value(target_type, expression.value),
        compute=lambda old, right: lower_managed_compound_operator(
            emitter._gen,
            expression,
            old,
            right,
            target_type,
            right_type,
            fresh_temp=emitter._fresh_temp,
        ),
        commit=lambda _old, replacement: [IRBinOp(left=target, op="=", right=replacement)],
        result_expr=lambda: target,
        old_temporary_owned=False,
        right_owned=bool(emitter._is_managed_type(right_type) and emitter._owns_expr(expression.value)),
        right_keep=managed_compound_keeps_rhs(
            emitter._gen,
            target_type,
            expression.op[:-1],
            right_type,
        ),
        release_replaced_old=True,
        c_type=emitter.iter_value_c,
        fresh_temp=emitter._fresh_temp,
        record_decl=emitter._func_var_decls.append,
        cleanup_active=emitter._exception_cleanup_active(),
        activate_cleanup=emitter._activate_cleanup_registration,
    )


def lower_generic_expression_statement(emitter, expression):
    """Consume a discarded caller-owned result at the statement boundary."""
    from ....ast_nodes import CallExpr, FieldAccessExpr
    from ..macro_boundaries import lower_assert_statement
    from ..managed_values import is_mutex_type

    assertion = lower_assert_statement(
        expression,
        lower_condition=emitter._expr,
        fresh_temp=emitter._fresh_temp,
        record_decl=emitter._func_var_decls.append,
        hosted=not emitter._gen.freestanding,
    )
    if assertion is not None:
        return assertion

    if (
        isinstance(expression, CallExpr)
        and isinstance(expression.callee, FieldAccessExpr)
        and expression.callee.field == "destroy"
        and is_mutex_type(
            emitter._gen,
            emitter._resolve_expr_type(expression.callee.obj),
        )
    ):
        return emitter._release_expression(expression.callee.obj)
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
    "lower_generic_managed_slot_assignment",
]
