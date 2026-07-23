"""Exact typed heap boxes for type-erased runtime boundaries."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ...ast_nodes import TypeExpr
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRDeref,
    IRLiteral,
    IRSizeof,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .types import type_to_c

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def box_exact_value(
    gen: IRLowerer,
    expr,
    type_expr: TypeExpr | None,
    *,
    prefix: str,
):
    """Evaluate ``expr`` once and copy its exact C representation to a box."""
    canonical = canonical_value_type(gen, type_expr)
    if canonical is None or is_scalar_void(canonical):
        return IRLiteral(text="NULL")

    gen.helpers.use("__btrc_safe_realloc")
    storage_c = value_storage_c_type(canonical)
    box_name = gen.fresh_temp(f"{prefix}_box")
    value_name = gen.fresh_temp(f"{prefix}_value")
    box = IRVar(name=box_name)
    value = IRVar(name=value_name)
    return IRStmtExpr(
        stmts=[
            IRVarDecl(c_type=CType(text=f"{storage_c}*"), name=box_name),
            IRVarDecl(c_type=CType(text=storage_c), name=value_name),
        ],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=value, op="=", right=expr),
                IRBinOp(
                    left=box,
                    op="=",
                    right=IRCast(
                        target_type=CType(text=f"{storage_c}*"),
                        expr=IRCall(
                            callee="__btrc_safe_realloc",
                            args=[
                                IRLiteral(text="NULL"),
                                IRSizeof(operand=IRDeref(expr=box)),
                            ],
                            helper_ref="__btrc_safe_realloc",
                        ),
                    ),
                ),
                IRBinOp(left=IRDeref(expr=box), op="=", right=value),
                IRCast(target_type=CType(text="void*"), expr=box),
            ]
        ),
    )


def unbox_exact_value(
    gen: IRLowerer,
    payload_call,
    type_expr: TypeExpr | None,
    *,
    prefix: str,
):
    """Copy a boxed value, free its transport, and yield the typed copy."""
    canonical = canonical_value_type(gen, type_expr)
    if canonical is None or is_scalar_void(canonical):
        return payload_call

    storage_c = value_storage_c_type(canonical)
    payload_name = gen.fresh_temp(f"{prefix}_payload")
    value_name = gen.fresh_temp(f"{prefix}_value")
    payload = IRVar(name=payload_name)
    value = IRVar(name=value_name)
    return IRStmtExpr(
        stmts=[
            IRVarDecl(c_type=CType(text="void*"), name=payload_name),
            IRVarDecl(c_type=CType(text=storage_c), name=value_name),
        ],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=payload, op="=", right=payload_call),
                IRBinOp(
                    left=value,
                    op="=",
                    right=IRDeref(
                        expr=IRCast(
                            target_type=CType(text=f"{storage_c}*"),
                            expr=payload,
                        )
                    ),
                ),
                IRCall(callee="free", args=[payload]),
                value,
            ]
        ),
    )


def canonical_value_type(
    gen: IRLowerer,
    type_expr: TypeExpr | None,
) -> TypeExpr | None:
    """Resolve typedefs while preserving use-site pointer and qualifiers."""
    from .type_resolution import canonical_type

    return canonical_type(type_expr, gen.analyzed.typedef_table)


def value_storage_c_type(type_expr: TypeExpr) -> str:
    """Return one assignable local-storage spelling for ``type_expr``."""
    return type_to_c(
        replace(
            type_expr,
            is_const=False,
            is_static=False,
            is_extern=False,
            is_volatile=False,
        )
    )


def is_scalar_void(type_expr: TypeExpr) -> bool:
    return type_expr.base == "void" and type_expr.pointer_depth == 0


__all__ = [
    "box_exact_value",
    "canonical_value_type",
    "is_scalar_void",
    "unbox_exact_value",
    "value_storage_c_type",
]
