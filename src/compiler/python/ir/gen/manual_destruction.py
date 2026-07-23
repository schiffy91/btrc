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
    IRFunctionRef,
    IRIf,
    IRLiteral,
    IRVar,
    IRVarDecl,
)
from .lvalues import value_c_type
from .types import CTypeRenderer


def lower_taken_delete(
    gen,
    target,
    type_expr,
    type_renderer: CTypeRenderer,
    *,
    edge_owner=None,
):
    """Move one lvalue to a temporary, clear its slot, then destroy it."""

    value_c = value_c_type(
        type_expr,
        gen.analyzed.class_table,
        type_renderer.render,
    )
    slot_name = gen.fresh_temp("__btrc_delete_slot")
    slot_decl = IRVarDecl(
        c_type=CType(text=f"{qualify_volatile_object(value_c, True)}*"),
        name=slot_name,
        init=IRAddressOf(expr=target),
    )
    gen.context.function_declarations.append(slot_decl)

    if gen.managed_values.is_arc(type_expr):
        helper = "__btrc_arc_destroy_edge" if edge_owner is not None else "__btrc_arc_destroy_slot"
        access = gen.cleanup_slots.ensure_arc_slot_adapter(CType(text=value_c))
        gen.helpers.use(helper)
        args = [
            IRCast(target_type=CType(text="volatile void*"), expr=IRVar(name=slot_name)),
            IRFunctionRef(name=access),
        ]
        if edge_owner is not None:
            args.append(edge_owner)
        args.append(gen.lifetime.arc_type_descriptor(type_expr))
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
    gen.context.function_declarations.append(value_decl)
    slot = IRDeref(expr=IRVar(name=slot_name))
    value = IRVar(name=value_name)

    if gen.managed_values.is_string(type_expr):
        destroy = gen.lifetime.release_value(value, type_expr)
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
