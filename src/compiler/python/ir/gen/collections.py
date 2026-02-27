"""Collection literal lowering: ListLiteral, MapLiteral → IR."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import ListLiteral, MapLiteral, TypeExpr
from ..nodes import IRCall, IRExpr, IRRawExpr
from .types import mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_list_literal(gen: IRGenerator, node: ListLiteral) -> IRExpr:
    """Lower [a, b, c] → List_new() + push calls.

    Since this is an expression, we use a GCC statement expression:
    ({btrc_List_int* __tmp = btrc_List_int_new(); btrc_List_int_push(__tmp, a); ... __tmp;})
    """
    from .expressions import lower_expr

    # Determine the list type from analyzer
    list_type = gen.analyzed.node_types.get(id(node))
    if list_type and list_type.generic_args:
        mangled = mangle_generic_type("List", list_type.generic_args)
    else:
        # Fallback: try to infer from first element
        mangled = "btrc_List_int"

    tmp = gen.fresh_temp("__list")
    parts = [f"{mangled}* {tmp} = {mangled}_new()"]
    for elem in node.elements:
        ir_elem = lower_expr(gen, elem)
        parts.append(f"{mangled}_push({tmp}, {_expr_text(ir_elem)})")
    parts.append(tmp)

    return IRRawExpr(text="({ " + "; ".join(parts) + "; })")


def lower_map_literal(gen: IRGenerator, node: MapLiteral) -> IRExpr:
    """Lower {k: v, ...} → Map_new() + put calls."""
    from .expressions import lower_expr

    map_type = gen.analyzed.node_types.get(id(node))
    if map_type and map_type.generic_args:
        mangled = mangle_generic_type("Map", map_type.generic_args)
    else:
        mangled = "btrc_Map_string_int"

    if not node.entries:
        return IRCall(callee=f"{mangled}_new", args=[])

    tmp = gen.fresh_temp("__map")
    parts = [f"{mangled}* {tmp} = {mangled}_new()"]
    for entry in node.entries:
        ir_key = lower_expr(gen, entry.key)
        ir_val = lower_expr(gen, entry.value)
        parts.append(f"{mangled}_put({tmp}, {_expr_text(ir_key)}, {_expr_text(ir_val)})")
    parts.append(tmp)

    return IRRawExpr(text="({ " + "; ".join(parts) + "; })")


def _expr_text(expr: IRExpr) -> str:
    from ..nodes import IRLiteral, IRVar, IRRawExpr as RawExpr
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, RawExpr):
        return expr.text
    return "/* complex */"
