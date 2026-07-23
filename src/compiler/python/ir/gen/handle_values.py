"""Move addressable opaque runtime handles out of their source slots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCommaExpr,
    IRDeref,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def consume_addressable_handle(
    gen: IRLowerer,
    obj,
    *,
    handle_c_type: str,
    prefix: str,
):
    """Move one lvalue handle and clear its source before it is consumed."""
    if not isinstance(obj, (IRVar, IRFieldAccess, IRIndex, IRDeref)):
        return obj
    slot_name = gen.fresh_temp(f"{prefix}_slot")
    handle_name = gen.fresh_temp(f"{prefix}_handle")
    slot = IRVar(name=slot_name)
    handle = IRVar(name=handle_name)
    return IRStmtExpr(
        stmts=[
            IRVarDecl(
                c_type=CType(text=f"{handle_c_type}* volatile*"),
                name=slot_name,
            ),
            IRVarDecl(c_type=CType(text=f"{handle_c_type}*"), name=handle_name),
        ],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=slot, op="=", right=IRAddressOf(expr=obj)),
                IRBinOp(left=handle, op="=", right=IRDeref(expr=slot)),
                IRBinOp(
                    left=IRDeref(expr=slot),
                    op="=",
                    right=IRLiteral(text="NULL"),
                ),
                handle,
            ]
        ),
    )


__all__ = ["consume_addressable_handle"]
