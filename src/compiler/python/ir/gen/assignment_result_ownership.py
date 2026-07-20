"""Ownership classification for assignment-expression results."""

from __future__ import annotations

from collections.abc import Callable


def assignment_pins_borrowed_target(gen, target) -> bool:
    """Whether assignment lowering promotes a borrowed target receiver."""
    from .assignment_ownership import (
        assignment_target_operands,
        kept_target_operands,
        property_projection,
    )
    from .managed_values import is_managed_type
    from .ownership import owns_result

    def type_of(expression):
        return gen.analyzed.node_types.get(id(expression))

    operands = assignment_target_operands(
        target,
        stabilize_receiver=lambda receiver: bool(
            owns_result(gen, receiver)
            or is_managed_type(gen, type_of(receiver))
            or property_projection(
                receiver,
                type_of=type_of,
                class_table=gen.analyzed.class_table,
            )
        ),
    )
    return bool(
        kept_target_operands(
            target,
            operands,
            type_of=type_of,
            is_managed=lambda type_expr: is_managed_type(gen, type_expr),
            owns=lambda expression: owns_result(gen, expression),
        )
    )


def virtual_assignment_rhs_owns_result(
    gen,
    target,
    value,
    *,
    type_of: Callable,
    owns: Callable,
    direct_property: Callable | None = None,
) -> bool:
    """Whether setter lowering must preserve the RHS as an owned result."""
    from .assignment_ownership import virtual_assignment_target

    if not virtual_assignment_target(
        gen,
        target,
        direct_property=direct_property,
    ):
        return False
    from .managed_values import is_managed_type

    if is_managed_type(gen, type_of(target)):
        return True
    if owns(value):
        return True
    from .prepared_values import requires_string_conversion

    return requires_string_conversion(
        gen,
        type_of(target),
        type_of(value),
    )


__all__ = [
    "assignment_pins_borrowed_target",
    "virtual_assignment_rhs_owns_result",
]
