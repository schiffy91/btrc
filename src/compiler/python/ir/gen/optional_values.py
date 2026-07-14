"""Typed zero values for short-circuited optional-chain expressions."""

from __future__ import annotations

from dataclasses import replace

from ..nodes import CType, IRCast, IRCompoundLiteral, IRLiteral
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
    result = type_expr
    seen: set[str] = set()
    while result is not None and result.base in gen.analyzed.typedef_table and result.base not in seen:
        seen.add(result.base)
        target = gen.analyzed.typedef_table[result.base]
        result = replace(
            target,
            pointer_depth=target.pointer_depth + result.pointer_depth,
            is_array=target.is_array or result.is_array,
            array_size=result.array_size or target.array_size,
            is_nullable=target.is_nullable or result.is_nullable,
        )
    return result


__all__ = ["optional_zero_value"]
