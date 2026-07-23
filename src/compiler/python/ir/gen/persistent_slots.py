"""Stabilize managed storage projections and their topology owner."""

from __future__ import annotations

from ...ast_nodes import FieldAccessExpr, IndexExpr
from ..nodes import CType, IRFieldAccess, IRIndex, IRVar, IRVarDecl


def stabilize_persistent_slot(
    gen,
    expression,
    target,
    *,
    render_type,
    resolve_type=None,
    fresh_temp=None,
    record_decl=None,
    prefix="__btrc_slot_owner",
):
    """Evaluate a class owner once and return its physical child slot."""
    from .managed_values import is_class_type

    resolve_type = resolve_type or (lambda node: gen.analyzed.node_types.get(id(node)))
    fresh_temp = fresh_temp or gen.fresh_temp
    record_decl = record_decl or gen.context.function_declarations.append

    owner_node = None
    owner_expr = None
    shape = ""
    if isinstance(expression, FieldAccessExpr) and isinstance(target, IRFieldAccess):
        owner_node = expression.obj
        owner_expr = target.obj
        shape = "field"
    elif (
        isinstance(expression, IndexExpr)
        and isinstance(expression.obj, FieldAccessExpr)
        and isinstance(target, IRIndex)
        and isinstance(target.obj, IRFieldAccess)
    ):
        owner_node = expression.obj.obj
        owner_expr = target.obj.obj
        shape = "index"
    owner_type = resolve_type(owner_node) if owner_node is not None else None
    if owner_expr is None or not is_class_type(gen, owner_type):
        return target, None, []

    declaration = IRVarDecl(
        c_type=CType(text=render_type(owner_type)),
        name=fresh_temp(prefix),
        init=owner_expr,
    )
    record_decl(declaration)
    owner = IRVar(name=declaration.name)
    if shape == "field":
        stable_target = IRFieldAccess(
            obj=owner,
            field=target.field,
            arrow=target.arrow,
        )
    else:
        stable_target = IRIndex(
            obj=IRFieldAccess(
                obj=owner,
                field=target.obj.field,
                arrow=target.obj.arrow,
            ),
            index=target.index,
        )
    return stable_target, owner, [declaration]


__all__ = ["stabilize_persistent_slot"]
