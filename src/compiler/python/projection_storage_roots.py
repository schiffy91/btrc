"""Backing-storage discovery for raw projection leaves."""

from __future__ import annotations

from dataclasses import dataclass

from .ast_nodes import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    IndexExpr,
    SelfExpr,
    SuperExpr,
    UnaryExpr,
)
from .raw_projection_carriers import is_raw_projection_carrier_type


@dataclass(frozen=True)
class ProjectionStorageRoot:
    """The nearest managed or temporary-struct backing expression."""

    expression: object
    managed: bool


def projection_storage_root(
    projection,
    *,
    type_of,
    is_managed,
    overridden,
    struct_table,
    direct=False,
):
    """Find the nearest storage root of one unconditional projection leaf."""
    if direct:
        projection_type = type_of(projection)
        if (
            projection_type is not None
            and is_managed(projection_type)
            and not isinstance(projection, (SelfExpr, SuperExpr))
        ):
            return ProjectionStorageRoot(expression=projection, managed=True)
        return None
    if isinstance(projection, CastExpr):
        return _recurse(projection.expr, type_of, is_managed, overridden, struct_table)
    if isinstance(projection, UnaryExpr) and projection.op == "*":
        return _recurse(projection.operand, type_of, is_managed, overridden, struct_table)
    if isinstance(projection, BinaryExpr) and projection.op in {"+", "-"}:
        candidates = (projection.left, projection.right) if projection.op == "+" else (projection.left,)
        for candidate in candidates:
            if is_raw_projection_carrier_type(
                type_of(candidate),
                is_managed=is_managed,
            ):
                return _recurse(candidate, type_of, is_managed, overridden, struct_table)
        return None
    if not isinstance(projection, (FieldAccessExpr, IndexExpr)):
        return None
    receiver = projection.obj
    if overridden(receiver):
        return None
    receiver_type = type_of(receiver)
    if receiver_type is not None and is_managed(receiver_type) and not isinstance(receiver, (SelfExpr, SuperExpr)):
        return ProjectionStorageRoot(expression=receiver, managed=True)
    if (
        isinstance(receiver, CallExpr)
        and receiver_type is not None
        and receiver_type.pointer_depth == 0
        and not receiver_type.is_array
        and receiver_type.base.removeprefix("struct ") in struct_table
    ):
        return ProjectionStorageRoot(expression=receiver, managed=False)
    return _recurse(receiver, type_of, is_managed, overridden, struct_table)


def _recurse(expression, type_of, is_managed, overridden, struct_table):
    return projection_storage_root(
        expression,
        type_of=type_of,
        is_managed=is_managed,
        overridden=overridden,
        struct_table=struct_table,
    )


__all__ = ["ProjectionStorageRoot", "projection_storage_root"]
