"""Ownership provenance for assignment expressions with virtual targets."""

from collections.abc import Callable

from ...ast_nodes import FieldAccessExpr, IndexExpr, SelfExpr, SuperExpr


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


def borrowed_projection_owner_operands(
    expression,
    *,
    owns: Callable,
    overridden: Callable = lambda _expression: False,
) -> list:
    """Return owned receivers backing an otherwise borrowed projection."""

    if overridden(expression) or owns(expression):
        return []
    if not isinstance(expression, (FieldAccessExpr, IndexExpr)):
        return []
    receiver = expression.obj
    if not overridden(receiver) and owns(receiver):
        return [receiver]
    return borrowed_projection_owner_operands(
        receiver,
        owns=owns,
        overridden=overridden,
    )


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
    "borrowed_projection_owner_operands",
    "kept_target_operands",
    "property_projection",
]
