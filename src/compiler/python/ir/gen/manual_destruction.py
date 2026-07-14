"""Take-clear lowering for explicit terminal destruction."""

from __future__ import annotations

from ..c_types import qualify_volatile_object
from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRDeref,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRVar,
    IRVarDecl,
)
from .types import type_to_c


def lower_taken_delete(gen, target, type_expr, *, edge_owner=None):
    """Move one lvalue to a temporary, clear its slot, then destroy it."""
    value_c = type_to_c(type_expr)
    slot_name = gen.fresh_temp("__btrc_delete_slot")
    value_name = gen.fresh_temp("__btrc_delete_value")
    slot_decl = IRVarDecl(
        c_type=CType(text=f"{qualify_volatile_object(value_c, True)}*"),
        name=slot_name,
        init=IRAddressOf(expr=target),
    )
    value_decl = IRVarDecl(
        c_type=CType(text=value_c),
        name=value_name,
        init=IRDeref(expr=IRVar(name=slot_name)),
    )
    gen._func_var_decls.extend((slot_decl, value_decl))
    slot = IRDeref(expr=IRVar(name=slot_name))
    value = IRVar(name=value_name)

    from .managed_values import (
        is_class_type,
        is_string_type,
        release_value,
        unlink_edge_value,
    )

    if is_class_type(gen, type_expr):
        from .arc_ops import arc_type_descriptor

        helper = "__btrc_arc_destroy"
        gen.use_helper(helper)
        destroy = IRCall(
            callee=helper,
            helper_ref=helper,
            args=[value, arc_type_descriptor(gen, type_expr)],
        )
    elif is_string_type(gen, type_expr):
        destroy = release_value(gen, value, type_expr)
    else:
        destroy = IRCall(callee="free", args=[value])

    guarded_destroy = IRIf(
        condition=IRBinOp(
            left=value,
            op="!=",
            right=IRLiteral(text="NULL"),
        ),
        then_block=IRBlock(stmts=[IRExprStmt(expr=destroy)]),
    )
    statements = [slot_decl, value_decl]
    if edge_owner is not None and is_class_type(gen, type_expr):
        statements.append(
            IRExprStmt(
                expr=unlink_edge_value(
                    gen,
                    value,
                    type_expr,
                    edge_owner,
                )
            )
        )
    statements.extend(
        [
            IRAssign(target=slot, value=IRLiteral(text="NULL")),
            guarded_destroy,
        ]
    )
    return statements


__all__ = ["lower_taken_delete"]
