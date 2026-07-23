"""Canonical type queries shared by IR lowering domains."""

from __future__ import annotations

from ...ast_nodes import TypeExpr
from ...type_composition import compose_type_expr
from ...type_identity import TypeIdentity


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
    return compose_type_expr(type_expr, resolved, reference_shape=resolved)


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


def substitute_concrete_type(type_expr, substitutions, typedefs, type_identity: TypeIdentity):
    """Substitute generics using canonical typedef targets for shape only."""
    return type_identity.substitute(
        type_expr,
        substitutions,
        reference_resolver=lambda value: canonical_type(value, typedefs),
    )


__all__ = [
    "canonical_type",
    "function_pointer_signature",
    "substitute_concrete_type",
]
