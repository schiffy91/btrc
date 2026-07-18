"""Canonical type queries shared by IR lowering domains."""

from __future__ import annotations

from dataclasses import replace

from ...ast_nodes import TypeExpr
from ...type_identity import substitute_type_expr


def canonical_type(
    type_expr: TypeExpr | None,
    typedefs: dict[str, TypeExpr],
    seen: frozenset[str] = frozenset(),
) -> TypeExpr | None:
    """Resolve typedef aliases while composing every use-site modifier."""
    if type_expr is None or type_expr.base not in typedefs or type_expr.base in seen:
        return type_expr
    resolved = canonical_type(
        typedefs[type_expr.base],
        typedefs,
        seen | {type_expr.base},
    )
    assert resolved is not None
    return replace(
        resolved,
        pointer_depth=resolved.pointer_depth + type_expr.pointer_depth,
        is_array=resolved.is_array or type_expr.is_array,
        array_size=type_expr.array_size or resolved.array_size,
        is_const=resolved.is_const or type_expr.is_const,
        is_nullable=resolved.is_nullable or type_expr.is_nullable,
        is_static=resolved.is_static or type_expr.is_static,
        is_extern=resolved.is_extern or type_expr.is_extern,
        is_volatile=resolved.is_volatile or type_expr.is_volatile,
        line=type_expr.line or resolved.line,
        col=type_expr.col or resolved.col,
    )


def function_pointer_signature(type_expr, typedefs):
    """Return ``(return, params...)`` only for a directly callable value."""
    resolved = canonical_type(type_expr, typedefs)
    if (
        resolved is None
        or resolved.base != "__fn_ptr"
        or resolved.pointer_depth != 0
        or resolved.is_array
        or not resolved.generic_args
    ):
        return None
    return resolved.generic_args


def substitute_concrete_type(type_expr, substitutions, typedefs):
    """Substitute generics using canonical typedef targets for shape only."""
    return substitute_type_expr(
        type_expr,
        substitutions,
        reference_resolver=lambda value: canonical_type(value, typedefs),
    )


__all__ = [
    "canonical_type",
    "function_pointer_signature",
    "substitute_concrete_type",
]
