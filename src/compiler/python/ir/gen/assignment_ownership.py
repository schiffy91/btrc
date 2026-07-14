"""Ownership provenance for assignment expressions with virtual targets."""

from collections.abc import Callable

from ...ast_nodes import FieldAccessExpr, IndexExpr, SelfExpr, SuperExpr
from ...class_storage import property_needs_backing
from ...index_protocol import indexed_protocol_info


def virtual_assignment_target(gen, target) -> bool:
    """Whether a setter call preserves the RHS +1 as the expression result."""
    if isinstance(target, IndexExpr):
        receiver_type = gen.analyzed.node_types.get(id(target.obj))
        return (
            indexed_protocol_info(
                receiver_type,
                gen.analyzed.class_table,
                method="set",
            )
            is not None
        )
    if not isinstance(target, FieldAccessExpr):
        return False
    receiver_type = gen.analyzed.node_types.get(id(target.obj))
    class_info = gen.analyzed.class_table.get(receiver_type.base) if receiver_type else None
    prop = class_info.properties.get(target.field) if class_info else None
    if prop is None:
        return False
    return not (
        isinstance(target.obj, SelfExpr)
        and gen.current_property_backing == target.field
        and property_needs_backing(prop)
    )


def assignment_target_operands(target, *, stabilize_receiver: Callable) -> list:
    """Collect target dependencies in source evaluation order.

    A receiver selected for stabilization is kept as one operand.  Otherwise
    raw field/index projections are followed until a receiver whose lifetime
    matters is reached.  This preserves lvalue shape while allowing the outer
    ownership boundary to evaluate each dependency exactly once.
    """
    if isinstance(target, FieldAccessExpr):
        return _receiver_operands(
            target.obj,
            stabilize_receiver=stabilize_receiver,
        )
    if isinstance(target, IndexExpr):
        return [
            *_receiver_operands(
                target.obj,
                stabilize_receiver=stabilize_receiver,
            ),
            target.index,
        ]
    return [target]


def kept_target_operands(target, operands, *, type_of: Callable, is_managed: Callable, owns: Callable) -> tuple:
    """Return borrowed managed operands that must outlive target evaluation."""
    if not isinstance(target, (FieldAccessExpr, IndexExpr)):
        return ()
    return tuple(
        operand
        for operand in operands
        if not isinstance(operand, (SelfExpr, SuperExpr)) and is_managed(type_of(operand)) and not owns(operand)
    )


def property_projection(target, *, type_of: Callable, class_table: dict) -> bool:
    """Whether a field-shaped expression is implemented by a getter."""
    if not isinstance(target, FieldAccessExpr):
        return False
    receiver_type = type_of(target.obj)
    if receiver_type is None:
        return False
    class_info = class_table.get(receiver_type.base)
    return bool(class_info is not None and target.field in class_info.properties)


def _receiver_operands(receiver, *, stabilize_receiver: Callable) -> list:
    if stabilize_receiver(receiver):
        return [receiver]
    return assignment_target_operands(
        receiver,
        stabilize_receiver=stabilize_receiver,
    )


__all__ = [
    "assignment_target_operands",
    "kept_target_operands",
    "property_projection",
    "virtual_assignment_target",
]
