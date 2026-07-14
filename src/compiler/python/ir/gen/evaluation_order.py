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


def operator_boundary_types(gen, left, right, operator: str):
    """Choose storage types for eager built-in operator sequencing.

    C macros and opaque imported values deliberately have no semantic btrc
    type.  A compatible concrete peer still supplies the value shape needed to
    evaluate that opaque operand once without falling back to C's implicit
    ``int``. Pointer offsets use ``ptrdiff_t``, the only standard integer type
    guaranteed to represent every defined same-array pointer displacement.
    The typed operator itself continues to see the operand as unresolved,
    leaving final compatibility checking to the C compiler.
    """
    left_type = gen.analyzed.node_types.get(id(left))
    right_type = gen.analyzed.node_types.get(id(right))
    return (
        _operator_boundary_type(
            gen,
            operator,
            left_type,
            right_type,
            is_left=True,
        ),
        _operator_boundary_type(
            gen,
            operator,
            right_type,
            left_type,
            is_left=False,
        ),
    )


def _operator_boundary_type(gen, operator, inferred, peer, *, is_left):
    if inferred is not None or peer is None:
        return inferred
    if operator in {"==", "!=", "<", ">", "<=", ">="}:
        return peer

    from ...ast_nodes import TypeExpr
    from ...numeric_semantics import is_floating_type, is_numeric_type

    enum_names = frozenset(gen.analyzed.enum_table)
    peer_is_numeric = is_numeric_type(peer, enum_names)
    peer_is_integral = peer_is_numeric and not is_floating_type(peer)
    if operator in {"*", "/", "%"} and peer_is_numeric:
        return peer
    if operator in {"&", "|", "^"} and peer_is_integral:
        return peer
    if operator in {"<<", ">>"}:
        return peer if not is_left and peer_is_integral else None
    if operator in {"+", "-"} and peer_is_numeric:
        return peer
    if not _raw_pointer_type(gen, peer):
        return None
    if operator == "+":
        return TypeExpr(base="ptrdiff_t")
    if operator == "-":
        return peer if is_left else TypeExpr(base="ptrdiff_t")
    return None


def _raw_pointer_type(gen, type_expr) -> bool:
    return bool(
        type_expr
        and (type_expr.pointer_depth > 0 or type_expr.is_array)
        and type_expr.base not in gen.analyzed.class_table
        and type_expr.base not in getattr(gen.analyzed, "interface_table", {})
    )


__all__ = [
    "has_observable_effect",
    "operand_c_type",
    "operator_boundary_types",
]
