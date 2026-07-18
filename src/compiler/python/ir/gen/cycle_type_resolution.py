"""Canonical type shapes used by cycle metadata traversal."""

from __future__ import annotations

from .type_resolution import canonical_type


def canonical_cycle_type(gen, type_expr):
    """Resolve the outer typedef before class-table and symbol queries."""
    return canonical_type(type_expr, gen.analyzed.typedef_table)


def cycle_type_key(type_expr) -> tuple:
    """Return a recursive traversal key for one already-canonical type."""
    return (
        type_expr.base,
        type_expr.pointer_depth,
        type_expr.is_array,
        type_expr.is_nullable,
        tuple(cycle_type_key(argument) for argument in type_expr.generic_args),
    )


def substitute_cycle_type(gen, type_expr, substitutions):
    """Resolve a cycle field without losing typedef-aware shape composition."""
    from .generics.core import _resolve_type

    return _resolve_type(
        type_expr,
        substitutions,
        gen.analyzed.typedef_table,
    )


__all__ = [
    "canonical_cycle_type",
    "cycle_type_key",
    "substitute_cycle_type",
]
