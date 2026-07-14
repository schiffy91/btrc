"""Source expressions whose evaluation can affect a sibling operand."""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FStringLiteral,
    IndexExpr,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    SpawnExpr,
    TernaryExpr,
    TupleLiteral,
    UnaryExpr,
)


def has_observable_effect(gen, node, *, type_of=None) -> bool:
    """Whether evaluating ``node`` can change a later operand's value."""
    if node is None:
        return False
    if isinstance(
        node,
        (
            AssignExpr,
            BraceInitializer,
            CallExpr,
            FStringLiteral,
            LambdaExpr,
            ListLiteral,
            MapLiteral,
            NewExpr,
            SpawnExpr,
        ),
    ):
        return True
    if isinstance(node, UnaryExpr):
        return node.op in {"++", "--"} or has_observable_effect(
            gen,
            node.operand,
            type_of=type_of,
        )
    if isinstance(node, BinaryExpr):
        return has_observable_effect(
            gen,
            node.left,
            type_of=type_of,
        ) or has_observable_effect(gen, node.right, type_of=type_of)
    if isinstance(node, TernaryExpr):
        return any(
            has_observable_effect(gen, child, type_of=type_of)
            for child in (node.condition, node.true_expr, node.false_expr)
        )
    if isinstance(node, CastExpr):
        return has_observable_effect(gen, node.expr, type_of=type_of)
    if isinstance(node, TupleLiteral):
        return any(has_observable_effect(gen, child, type_of=type_of) for child in node.elements)
    if isinstance(node, FieldAccessExpr):
        if node.optional or has_observable_effect(gen, node.obj, type_of=type_of):
            return True
        receiver_type = _canonical_receiver_type(
            gen,
            (type_of or _analyzed_type(gen))(node.obj),
        )
        class_info = gen.analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
        return bool(class_info is not None and node.field in class_info.properties)
    if isinstance(node, IndexExpr):
        if has_observable_effect(gen, node.obj, type_of=type_of):
            return True
        if has_observable_effect(gen, node.index, type_of=type_of):
            return True
        from ...index_protocol import indexed_protocol_info

        receiver_type = _canonical_receiver_type(
            gen,
            (type_of or _analyzed_type(gen))(node.obj),
        )
        return bool(
            receiver_type is not None
            and indexed_protocol_info(
                receiver_type,
                gen.analyzed.class_table,
                method="get",
            )
        )
    return False


def _analyzed_type(gen):
    return lambda node: gen.analyzed.node_types.get(id(node))


def _canonical_receiver_type(gen, type_expr):
    from .type_resolution import canonical_type

    return canonical_type(type_expr, gen.analyzed.typedef_table)


def operand_c_type(gen, node, type_expr, *, render):
    """Render the C value type without changing enumerator semantics."""
    from ...ast_nodes import Identifier

    if isinstance(node, Identifier):
        if any(node.name in values for values in gen.analyzed.enum_table.values()):
            return "int"
    return render(type_expr)


__all__ = ["has_observable_effect", "operand_c_type"]
