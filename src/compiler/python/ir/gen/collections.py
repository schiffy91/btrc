"""Collection literal lowering: ListLiteral, MapLiteral → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import ListLiteral, MapLiteral
from ..nodes import (
    CType,
    IRCall,
    IRExpr,
    IRExprStmt,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .types import mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_list_literal(gen: IRGenerator, node: ListLiteral) -> IRExpr:
    """Lower [a, b, c] → List_new() + push calls.

    Uses IRStmtExpr to produce a GCC statement expression:
    ({btrc_List_int* __tmp = btrc_List_int_new(); btrc_List_int_push(__tmp, a); ... __tmp;})
    """
    from .expressions import lower_expr

    # Determine the list type from analyzer
    list_type = gen.analyzed.node_types.get(id(node))
    if list_type and list_type.generic_args:
        mangled = mangle_generic_type(list_type.base, list_type.generic_args)
    elif node.elements:
        # Infer from first element's type
        elem_type = gen.analyzed.node_types.get(id(node.elements[0]))
        if elem_type:
            mangled = mangle_generic_type("Vector", [elem_type])
        else:
            mangled = "btrc_Vector_int"
    else:
        mangled = "btrc_Vector_int"

    tmp = gen.fresh_temp("__list")
    stmts = [IRVarDecl(
        c_type=CType(text=f"{mangled}*"),
        name=tmp,
        init=IRCall(callee=f"{mangled}_new", args=[]),
    )]
    for elem in node.elements:
        ir_elem = lower_expr(gen, elem)
        stmts.append(IRExprStmt(
            expr=IRCall(callee=f"{mangled}_push", args=[IRVar(name=tmp), ir_elem]),
        ))

    return IRStmtExpr(stmts=stmts, result=IRVar(name=tmp))


def lower_map_literal(gen: IRGenerator, node: MapLiteral) -> IRExpr:
    """Lower {k: v, ...} → Map_new() + put calls."""
    from .expressions import lower_expr

    map_type = gen.analyzed.node_types.get(id(node))
    if map_type and map_type.generic_args:
        mangled = mangle_generic_type(map_type.base, map_type.generic_args)
    elif node.entries:
        # Infer from first entry's key/value types
        key_type = gen.analyzed.node_types.get(id(node.entries[0].key))
        val_type = gen.analyzed.node_types.get(id(node.entries[0].value))
        if key_type and val_type:
            mangled = mangle_generic_type("Map", [key_type, val_type])
        else:
            mangled = "btrc_Map_string_int"
    else:
        mangled = "btrc_Map_string_int"

    if not node.entries:
        return IRCall(callee=f"{mangled}_new", args=[])

    tmp = gen.fresh_temp("__map")
    stmts = [IRVarDecl(
        c_type=CType(text=f"{mangled}*"),
        name=tmp,
        init=IRCall(callee=f"{mangled}_new", args=[]),
    )]
    for entry in node.entries:
        ir_key = lower_expr(gen, entry.key)
        ir_val = lower_expr(gen, entry.value)
        stmts.append(IRExprStmt(
            expr=IRCall(callee=f"{mangled}_put",
                        args=[IRVar(name=tmp), ir_key, ir_val]),
        ))

    return IRStmtExpr(stmts=stmts, result=IRVar(name=tmp))
