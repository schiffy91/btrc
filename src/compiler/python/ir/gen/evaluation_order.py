"""Source expressions whose evaluation can affect a sibling operand."""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CallExpr,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    FStringLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SizeofExpr,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    TupleLiteral,
    UnaryExpr,
)


def borrowed_value_can_be_pinned(node) -> bool:
    """Whether a borrowed expression may be retained for local stabilization."""
    # Implicit receivers already live for the invocation's dynamic extent.
    # Retaining them from a destructor would violate ARC's DESTROYING state.
    return not isinstance(node, (SelfExpr, SuperExpr))


def has_observable_effect(gen, node, *, type_of=None) -> bool:
    """Whether evaluating ``node`` can change a later operand's value."""
    if node is None:
        return False
    if isinstance(node, Identifier):
        if _enum_constant_identifier(gen, node):
            return False
        return (type_of or _analyzed_type(gen))(node) is None
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


def reorder_inert(gen, node) -> bool:
    """Whether evaluating ``node`` cannot observe or change sibling state."""
    if isinstance(
        node,
        (
            BoolLiteral,
            CharLiteral,
            FloatLiteral,
            IntLiteral,
            NullLiteral,
            StringLiteral,
        ),
    ):
        return True
    if isinstance(node, Identifier):
        return _enum_constant_identifier(gen, node)
    if isinstance(node, CastExpr):
        return reorder_inert(gen, node.expr)
    if isinstance(node, SizeofExpr):
        return True
    if isinstance(node, UnaryExpr) and node.op in {"+", "-", "!", "~"}:
        return reorder_inert(gen, node.operand)
    return False


def operands_require_order(gen, nodes) -> bool:
    """Whether unspecified C operand order can change source semantics."""
    effects = [has_observable_effect(gen, node) for node in nodes]
    for left_index, left in enumerate(nodes):
        for right_index in range(left_index + 1, len(nodes)):
            right = nodes[right_index]
            if effects[left_index] and not reorder_inert(gen, right):
                return True
            if effects[right_index] and not reorder_inert(gen, left):
                return True
    return False


def source_order_pin_flags(
    gen,
    nodes,
    types,
    owned,
    *,
    type_of=None,
    is_managed=None,
    effects=None,
) -> list[bool]:
    """Pin earlier borrowed managed values across later side effects."""
    if effects is None:
        effects = [has_observable_effect(gen, node, type_of=type_of) for node in nodes]
    if is_managed is None:
        from .managed_values import is_managed_type

        def is_managed(value):
            return is_managed_type(gen, value)

    return [
        bool(
            borrowed_value_can_be_pinned(nodes[index])
            and not owned[index]
            and is_managed(types[index])
            and any(effects[index + 1 :])
        )
        for index in range(len(nodes))
    ]


def _analyzed_type(gen):
    return lambda node: gen.analyzed.node_types.get(id(node))


def _canonical_receiver_type(gen, type_expr):
    from .type_resolution import canonical_type

    return canonical_type(type_expr, gen.analyzed.typedef_table)


def _enum_constant_identifier(gen, node) -> bool:
    enum_table = getattr(gen.analyzed, "enum_table", {})
    return any(node.name in values for values in enum_table.values())


def operand_c_type(gen, node, type_expr, *, render):
    """Render the C value type without changing enumerator semantics."""
    from ...ast_nodes import Identifier

    if isinstance(node, Identifier):
        if any(node.name in values for values in gen.analyzed.enum_table.values()):
            return "int"
    return render(type_expr)


def reject_opaque_ordering(node, context: str, *, typed_declaration: bool = False) -> None:
    """Reject an opaque C value that cannot be sequenced without guessing its type."""
    from .errors import CodegenError

    remedy = "cast it explicitly"
    if typed_declaration:
        remedy += " or provide a typed declaration"
    raise CodegenError(f"opaque C operand at {node.line}:{node.col} precedes an ordered sibling in {context}; {remedy}")


__all__ = [
    "borrowed_value_can_be_pinned",
    "has_observable_effect",
    "operand_c_type",
    "operands_require_order",
    "reject_opaque_ordering",
    "reorder_inert",
    "source_order_pin_flags",
]
