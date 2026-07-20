"""Typed zero values for short-circuited optional-chain expressions."""

from __future__ import annotations

from ..nodes import CType, IRCast, IRCompoundLiteral, IRLiteral
from .type_resolution import canonical_type
from .types import type_to_c


def optional_zero_value(gen, type_expr):
    """Return the strict-C zero/null value for an analyzed expression type."""
    canonical = _canonical_type(gen, type_expr)
    if canonical is None:
        return IRLiteral(text="0")
    if canonical.base == "void":
        return IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0"))
    c_type = type_to_c(type_expr)
    if (
        canonical.pointer_depth > 0
        or canonical.is_array
        or canonical.base == "string"
        or canonical.base in gen.analyzed.class_table
        or c_type.endswith("*")
    ):
        return IRLiteral(text="NULL")
    if (
        canonical.base == "Tuple"
        or canonical.base.removeprefix("struct ") in gen.analyzed.struct_table
        or canonical.base in gen.analyzed.rich_enum_table
    ):
        return IRCompoundLiteral(c_type=CType(text=c_type), fields=[])
    return IRLiteral(text="0")


def _canonical_type(gen, type_expr):
    return canonical_type(type_expr, gen.analyzed.typedef_table)


__all__ = ["optional_zero_value"]
