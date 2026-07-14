"""Owner-aware lowering atoms for class-resident ``Mutex<T>`` handles."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRFieldAccess,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .errors import CodegenError
from .type_resolution import canonical_type


def mutex_value_type(gen, type_expr):
    """Return the canonical value type of one direct ``Mutex<T>`` handle."""
    canonical = canonical_type(type_expr, gen.analyzed.typedef_table)
    if (
        canonical is None
        or canonical.is_array
        or canonical.pointer_depth != 0
        or canonical.base != "Mutex"
        or len(canonical.generic_args) != 1
    ):
        return None
    return canonical.generic_args[0]


def mutex_holds_class(gen, type_expr) -> bool:
    """Whether a Mutex field owns a class edge visible to cycle collection."""
    value_type = mutex_value_type(gen, type_expr)
    if value_type is None:
        return False
    from .managed_values import is_class_type

    return is_class_type(gen, value_type)


def replace_mutex_field(gen, slot, replacement, owner):
    """Bind and commit one Mutex field, then terminally destroy its old handle."""
    gen.use_helper("__btrc_mutex_val_replace_owner")
    return IRCall(
        callee="__btrc_mutex_val_replace_owner",
        helper_ref="__btrc_mutex_val_replace_owner",
        args=[IRAddressOf(expr=slot), replacement, owner],
    )


def lower_mutex_field_store(
    gen,
    expression,
    *,
    receiver_type,
    field_type,
    field_name,
    lower_expr,
    lower_value,
    c_type,
    fresh_temp,
    record_decl,
):
    """Sequence one owner-aware Mutex field assignment exactly once."""
    if expression.op != "=":
        raise CodegenError("Mutex fields do not support compound assignment")
    receiver_decl = IRVarDecl(
        c_type=CType(text=c_type(receiver_type)),
        name=fresh_temp("__btrc_mutex_owner"),
    )
    value_decl = IRVarDecl(
        c_type=CType(text=c_type(field_type)),
        name=fresh_temp("__btrc_mutex_field"),
    )
    record_decl(receiver_decl)
    record_decl(value_decl)
    receiver = IRVar(name=receiver_decl.name)
    value = IRVar(name=value_decl.name)
    field = IRFieldAccess(obj=receiver, field=field_name, arrow=True)
    from .mutex_values import consume_mutex_handle

    lowered_value = consume_mutex_handle(
        gen,
        lower_value(field_type, expression.value),
    )
    return IRStmtExpr(
        stmts=[receiver_decl, value_decl],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(
                    left=receiver,
                    op="=",
                    right=lower_expr(expression.target.obj),
                ),
                IRBinOp(
                    left=value,
                    op="=",
                    right=lowered_value,
                ),
                replace_mutex_field(gen, field, value, receiver),
                field,
            ]
        ),
    )


def destroy_mutex_field(gen, field):
    """Take-and-clear one Mutex field before its throwing terminal cleanup."""
    from .mutex_values import consume_mutex_handle

    gen.use_helper("__btrc_mutex_val_destroy")
    return IRCall(
        callee="__btrc_mutex_val_destroy",
        helper_ref="__btrc_mutex_val_destroy",
        args=[consume_mutex_handle(gen, field)],
    )


def visit_mutex_field(gen, type_expr, field, visitor, context):
    """Expose a bound Mutex class payload as an exact typed graph slot."""
    if not mutex_holds_class(gen, type_expr):
        return None
    gen.use_helper("__btrc_mutex_val_visit")
    return IRCall(
        callee="__btrc_mutex_val_visit",
        helper_ref="__btrc_mutex_val_visit",
        args=[field, visitor, context],
    )


def null_mutex_handle():
    return IRLiteral(text="NULL")


__all__ = [
    "destroy_mutex_field",
    "lower_mutex_field_store",
    "mutex_holds_class",
    "mutex_value_type",
    "null_mutex_handle",
    "replace_mutex_field",
    "visit_mutex_field",
]
