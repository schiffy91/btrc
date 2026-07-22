"""Backing storage that must outlive a borrowed array projection."""

from __future__ import annotations

from dataclasses import dataclass

from ...projection_storage_roots import projection_storage_root
from ...raw_projection_carriers import (
    is_raw_projection_carrier_type,
    raw_projection_carrier,
    unconditional_projection_leaves,
)


@dataclass(frozen=True)
class ProjectionStorageOperand:
    """One source expression stabilized before deriving an array view."""

    expression: object
    owned: bool
    keep: bool


def projection_storage_operands(
    expression,
    *,
    type_of,
    is_managed,
    owns,
    overridden,
    struct_table,
    return_alias_argument=lambda _expression: None,
):
    """Return the nearest storage expression backing a raw projection."""
    if overridden(expression):
        return ()
    carrier = raw_projection_carrier(
        expression,
        type_of=type_of,
        is_raw_carrier=lambda value: is_raw_projection_carrier_type(
            value,
            is_managed=is_managed,
        ),
        is_direct_storage=lambda value: bool((value_type := type_of(value)) and is_managed(value_type)),
        return_alias_argument=return_alias_argument,
    )
    operands = []
    for leaf in unconditional_projection_leaves(carrier):
        root = projection_storage_root(
            leaf.expression,
            type_of=type_of,
            is_managed=is_managed,
            overridden=overridden,
            struct_table=struct_table,
            direct=leaf.direct_storage,
        )
        if root is None:
            continue
        owned = bool(root.managed and owns(root.expression))
        operands.append(
            ProjectionStorageOperand(
                root.expression,
                owned=owned,
                keep=bool(root.managed and not owned),
            )
        )
    return tuple(operands)


def evaluate_with_operand_overrides(
    overrides,
    *,
    values,
    operation,
    types=None,
    type_values=None,
):
    """Evaluate one projection with earlier stabilized storage installed."""
    previous = {key: values.get(key) for key in overrides}
    typed = {key: types[key] for key in overrides if types and key in types}
    previous_types = {key: type_values.get(key) for key in typed} if type_values is not None else {}
    values.update(overrides)
    if type_values is not None:
        type_values.update(typed)
    try:
        return operation()
    finally:
        _restore(values, previous)
        if type_values is not None:
            _restore(type_values, previous_types)


def _restore(mapping, previous):
    for key, value in previous.items():
        if value is None:
            mapping.pop(key, None)
        else:
            mapping[key] = value


__all__ = [
    "ProjectionStorageOperand",
    "evaluate_with_operand_overrides",
    "projection_storage_operands",
]
