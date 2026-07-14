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
    IRCast,
    IRDeref,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRVar,
    IRVarDecl,
)
from .lvalues import value_c_type
from .types import type_to_c


def lower_taken_delete(gen, target, type_expr, *, edge_owner=None):
    """Move one lvalue to a temporary, clear its slot, then destroy it."""
    from .managed_values import is_class_type, is_string_type, release_value

    value_c = value_c_type(type_expr, gen.analyzed.class_table, type_to_c)
    slot_name = gen.fresh_temp("__btrc_delete_slot")
    slot_decl = IRVarDecl(
        c_type=CType(text=f"{qualify_volatile_object(value_c, True)}*"),
        name=slot_name,
        init=IRAddressOf(expr=target),
    )
    gen._func_var_decls.append(slot_decl)

    if is_class_type(gen, type_expr):
        from .arc_ops import arc_type_descriptor
        from .cleanup_slots import ensure_arc_slot_adapter

        helper = "__btrc_arc_destroy_edge" if edge_owner is not None else "__btrc_arc_destroy_slot"
        access = ensure_arc_slot_adapter(gen, CType(text=value_c))
        gen.use_helper(helper)
        args = [
            IRCast(target_type=CType(text="volatile void*"), expr=IRVar(name=slot_name)),
            IRVar(name=access),
        ]
        if edge_owner is not None:
            args.append(edge_owner)
        args.append(arc_type_descriptor(gen, type_expr))
        return [
            slot_decl,
            IRExprStmt(
                expr=IRCall(
                    callee=helper,
                    helper_ref=helper,
                    args=args,
                )
            ),
        ]

    value_name = gen.fresh_temp("__btrc_delete_value")
    value_decl = IRVarDecl(
        c_type=CType(text=value_c),
        name=value_name,
        init=IRDeref(expr=IRVar(name=slot_name)),
    )
    gen._func_var_decls.append(value_decl)
    slot = IRDeref(expr=IRVar(name=slot_name))
    value = IRVar(name=value_name)

    if is_string_type(gen, type_expr):
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
    statements.extend(
        [
            IRAssign(target=slot, value=IRLiteral(text="NULL")),
            guarded_destroy,
        ]
    )
    return statements


__all__ = ["lower_taken_delete"]
