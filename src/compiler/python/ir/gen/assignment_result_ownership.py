"""Ownership classification for assignment-expression results."""

from __future__ import annotations


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


__all__ = ["assignment_pins_borrowed_target"]
