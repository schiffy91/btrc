"""Typedef resolution shared by declaration policies and type analysis."""

from __future__ import annotations

from ...type_composition import compose_type_expr


def canonical_declaration_type(type_expr, typedefs, seen=None):
    """Resolve aliases while preserving modifiers written at the use site."""
    if type_expr is None or type_expr.base not in typedefs:
        return type_expr
    seen = set() if seen is None else seen
    if type_expr.base in seen:
        return type_expr
    seen.add(type_expr.base)
    resolved = canonical_declaration_type(typedefs[type_expr.base], typedefs, seen)
    return compose_type_expr(type_expr, resolved, reference_shape=resolved)


__all__ = ["canonical_declaration_type"]
