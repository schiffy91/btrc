"""Ownership-safe collection literal lowering."""

from __future__ import annotations

from ...ast_nodes import ListLiteral, MapLiteral, TypeExpr
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .call_boundary import CallOperand
from .prepared_values import prepare_normal_value, prepared_value_pin_flags
from .types import CTypeRenderer


def lower_list_literal(
    gen,
    node: ListLiteral,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Build a typed list/vector and consume caller-owned elements."""
    list_type = gen.analyzed.node_types.get(id(node))
    element_type = (
        list_type.generic_args[0]
        if list_type is not None and list_type.generic_args
        else gen.analyzed.node_types.get(id(node.elements[0]))
        if node.elements
        else TypeExpr(base="int")
    )
    if list_type is None:
        list_type = TypeExpr(base="Vector", generic_args=[element_type])
    mangled = gen.type_identity.specialization_symbol(list_type.base, list_type.generic_args)
    declarations, sequence, collection, result = _collection_storage(
        gen,
        list_type,
        mangled,
        "__list",
    )
    for element in node.elements:
        sequence.append(
            _prepared_effect(
                gen,
                [(element, element_type)],
                type_renderer,
                default_arguments,
                lambda values, element=element: IRCall(
                    callee=f"{mangled}_push",
                    args=[collection, values[id(element)]],
                ),
            )
        )
    _finish_collection(sequence, collection, result)
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def lower_map_literal(
    gen,
    node: MapLiteral,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Build a typed map and consume caller-owned keys and values."""
    map_type = gen.analyzed.node_types.get(id(node))
    if map_type is not None and len(map_type.generic_args) == 2:
        key_type, value_type = map_type.generic_args
    elif node.entries:
        key_type = gen.analyzed.node_types.get(id(node.entries[0].key)) or TypeExpr(base="string")
        value_type = gen.analyzed.node_types.get(id(node.entries[0].value)) or TypeExpr(base="int")
        map_type = TypeExpr(base="Map", generic_args=[key_type, value_type])
    else:
        key_type, value_type = TypeExpr(base="string"), TypeExpr(base="int")
        map_type = TypeExpr(base="Map", generic_args=[key_type, value_type])
    mangled = gen.type_identity.specialization_symbol(map_type.base, map_type.generic_args)
    if not node.entries and not gen.exception_cleanup_active():
        return IRCall(callee=f"{mangled}_new", args=[])

    declarations, sequence, collection, result = _collection_storage(
        gen,
        map_type,
        mangled,
        "__map",
    )
    for entry in node.entries:
        sequence.append(
            _prepared_effect(
                gen,
                [(entry.key, key_type), (entry.value, value_type)],
                type_renderer,
                default_arguments,
                lambda values, entry=entry: IRCall(
                    callee=f"{mangled}_put",
                    args=[
                        collection,
                        values[id(entry.key)],
                        values[id(entry.value)],
                    ],
                ),
            )
        )
    _finish_collection(sequence, collection, result)
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _prepared_effect(
    gen,
    values,
    type_renderer: CTypeRenderer,
    default_arguments,
    build,
):
    prepared = [
        (
            node,
            prepare_normal_value(
                gen,
                node,
                target_type,
                type_renderer,
                default_arguments=default_arguments,
            ),
        )
        for node, target_type in values
    ]
    if len(prepared) == 1 and not prepared[0][1].owned:
        node, value = prepared[0]
        return build({id(node): value.value})
    pins = prepared_value_pin_flags(gen, prepared)
    operands = []
    for index, (node, value) in enumerate(prepared):
        operands.append(
            CallOperand(
                node=node,
                type_expr=value.effective_type,
                c_type=type_renderer.render(value.effective_type),
                pin=pins[index],
                owned=value.owned,
                lowered=value.value,
            )
        )
    return gen.ownership.boundaries.sequence(
        operands,
        lower_expr=lambda _node: None,
        build_call=build,
        result_c_type=None,
    )


def _collection_storage(gen, type_expr, mangled, prefix):
    temporary = IRVarDecl(
        c_type=CType(text=f"{mangled}*"),
        name=gen.fresh_temp(prefix),
    )
    gen.context.function_declarations.append(temporary)
    declarations = [temporary]
    collection = IRVar(name=temporary.name)
    sequence = [
        IRBinOp(
            left=collection,
            op="=",
            right=IRCall(callee=f"{mangled}_new", args=[]),
        )
    ]
    result = collection
    if gen.exception_cleanup_active():
        from .temporary_cleanup import cleanup_registration

        cleanup_decls, cleanup_exprs = cleanup_registration(
            gen,
            temporary,
            type_expr,
            "__btrc_collection_cleanup",
        )
        declarations.extend(cleanup_decls)
        sequence.extend(cleanup_exprs)
        result_decl = IRVarDecl(
            c_type=CType(text=f"{mangled}*"),
            name=gen.fresh_temp("__btrc_collection_result"),
        )
        gen.context.function_declarations.append(result_decl)
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
    return declarations, sequence, collection, result


def _finish_collection(sequence, collection, result):
    if result is not collection:
        sequence.extend(
            [
                IRBinOp(left=result, op="=", right=collection),
                IRBinOp(
                    left=collection,
                    op="=",
                    right=IRLiteral(text="NULL"),
                ),
            ]
        )
    sequence.append(result)


__all__ = ["lower_list_literal", "lower_map_literal"]
