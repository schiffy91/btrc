"""Collection literal lowering: ListLiteral, MapLiteral → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import ListLiteral, MapLiteral
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRExpr,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .types import mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_list_literal(gen: IRGenerator, node: ListLiteral) -> IRExpr:
    """Lower [a, b, c] → List_new() + push calls.

    The temporary declaration is safe to hoist; allocation and pushes remain a
    standard-C comma expression at the literal's semantic evaluation site.
    """
    from .expressions import lower_expr
    from .ownership_boundary import sequence_owned_operands

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
    declarations = [
        IRVarDecl(
            c_type=CType(text=f"{mangled}*"),
            name=tmp,
        )
    ]
    sequence = [IRBinOp(left=IRVar(name=tmp), op="=", right=IRCall(callee=f"{mangled}_new", args=[]))]
    for elem in node.elements:

        def push_element(elem=elem):
            return IRCall(
                callee=f"{mangled}_push",
                args=[IRVar(name=tmp), lower_expr(gen, elem)],
            )

        sequence.append(
            sequence_owned_operands(
                gen,
                [elem],
                build=push_element,
                result_type=None,
            )
            or push_element()
        )

    sequence.append(IRVar(name=tmp))
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def lower_map_literal(gen: IRGenerator, node: MapLiteral) -> IRExpr:
    """Lower {k: v, ...} → Map_new() + put calls."""
    from .expressions import lower_expr
    from .ownership_boundary import sequence_owned_operands

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
    declarations = [
        IRVarDecl(
            c_type=CType(text=f"{mangled}*"),
            name=tmp,
        )
    ]
    sequence = [IRBinOp(left=IRVar(name=tmp), op="=", right=IRCall(callee=f"{mangled}_new", args=[]))]
    for entry in node.entries:

        def put_entry(entry=entry):
            return IRCall(
                callee=f"{mangled}_put",
                args=[
                    IRVar(name=tmp),
                    lower_expr(gen, entry.key),
                    lower_expr(gen, entry.value),
                ],
            )

        sequence.append(
            sequence_owned_operands(
                gen,
                [entry.key, entry.value],
                build=put_entry,
                result_type=None,
            )
            or put_entry()
        )

    sequence.append(IRVar(name=tmp))
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )
