"""Declarator-aware qualifier provenance through user typedefs.

``TypeExpr`` intentionally keeps a compact shape, but a typedef boundary can
move a qualifier below a use-site pointer.  These queries retain that boundary
without changing the public AST representation.  Depth zero is the declared
object; depth one is the object reached through one pointer/array layer.
"""

from __future__ import annotations

from .ast_nodes import TypeExpr
from .type_composition import (
    nullable_collapses_reference_layer,
    resolved_reference_shape,
    strip_outer_storage,
)

_IMPLICIT_RAW_POINTER_BASES = frozenset({"Mutex", "Thread", "string"})


def volatile_qualifier_depths(
    type_expr: TypeExpr | None,
    typedefs: dict[str, TypeExpr],
    seen: frozenset[str] = frozenset(),
) -> frozenset[int]:
    """Return every storage depth carrying ``volatile``.

    btrc's explicit ``volatile`` qualifies the represented storage object (or
    each element of an array).  A qualifier inherited from a typedef is shifted
    below any pointer/array shell added at the use site.
    """

    if type_expr is None:
        return frozenset()
    depths: set[int] = set()
    if type_expr.is_volatile:
        depths.add(1 if type_expr.is_array else 0)
    target = _typedef_target(type_expr, typedefs, seen)
    if target is not None:
        shift = _applied_storage_layers(type_expr, target)
        depths.update(
            depth + shift
            for depth in volatile_qualifier_depths(
                target,
                typedefs,
                seen | {type_expr.base},
            )
        )
    return frozenset(depths)


def const_qualifier_depths(
    type_expr: TypeExpr | None,
    typedefs: dict[str, TypeExpr],
    seen: frozenset[str] = frozenset(),
) -> frozenset[int]:
    """Return every storage depth carrying ``const`` under C declarators."""

    if type_expr is None:
        return frozenset()
    target = _typedef_target(type_expr, typedefs, seen)
    shift = _applied_storage_layers(type_expr, target)
    depths: set[int] = set()
    if type_expr.is_const:
        # ``const Alias`` qualifies the alias object.  Without an alias the
        # qualifier prefixes the rendered C base and therefore sits below all
        # explicit (and selected intrinsic) pointer layers.
        implicit = int(target is None and type_expr.base in _IMPLICIT_RAW_POINTER_BASES)
        depths.add(shift + implicit)
    if target is not None:
        depths.update(
            depth + shift
            for depth in const_qualifier_depths(
                target,
                typedefs,
                seen | {type_expr.base},
            )
        )
    return frozenset(depths)


def effective_outer_volatile(
    type_expr: TypeExpr | None,
    typedefs: dict[str, TypeExpr],
    seen: frozenset[str] = frozenset(),
) -> bool:
    """Whether this declarator's represented storage is volatile.

    An array declaration represents its elements, so it inherits volatility
    from an element alias.  A pointer shell is the boundary that makes the
    inherited qualifier belong to a pointee instead (``V*`` is not itself
    volatile when ``V`` aliases ``volatile int``).
    """

    if type_expr is None:
        return False
    if type_expr.is_volatile:
        return True
    target = _typedef_target(type_expr, typedefs, seen)
    if target is None or _applied_pointer_layers(type_expr, target) > 0:
        return False
    return effective_outer_volatile(
        target,
        typedefs,
        seen | {type_expr.base},
    )


def effective_outer_const(type_expr: TypeExpr | None, typedefs: dict[str, TypeExpr]) -> bool:
    """Whether the declared object itself is effectively const."""

    return 0 in const_qualifier_depths(type_expr, typedefs)


def strip_outer_storage_through_typedef(
    type_expr: TypeExpr | None,
    typedefs: dict[str, TypeExpr],
    seen: frozenset[str] = frozenset(),
) -> TypeExpr | None:
    """Remove one pointer/array layer without flattening its inner alias."""

    if type_expr is None:
        return None
    if type_expr.is_array:
        return strip_outer_storage(type_expr, array=True)
    if type_expr.pointer_depth > 0:
        return strip_outer_storage(type_expr)
    target = _typedef_target(type_expr, typedefs, seen)
    if target is None:
        return None
    return strip_outer_storage_through_typedef(
        target,
        typedefs,
        seen | {type_expr.base},
    )


def _typedef_target(
    type_expr: TypeExpr,
    typedefs: dict[str, TypeExpr],
    seen: frozenset[str],
) -> TypeExpr | None:
    if type_expr.generic_args or type_expr.base in seen:
        return None
    return typedefs.get(type_expr.base)


def _applied_storage_layers(type_expr: TypeExpr, target: TypeExpr | None) -> int:
    reference_shape = resolved_reference_shape(target) if target is not None else False
    pointer_depth = type_expr.pointer_depth - int(
        nullable_collapses_reference_layer(
            type_expr,
            base_is_reference=reference_shape,
        )
    )
    return pointer_depth + int(type_expr.is_array)


def _applied_pointer_layers(type_expr: TypeExpr, target: TypeExpr | None) -> int:
    reference_shape = resolved_reference_shape(target) if target is not None else False
    return type_expr.pointer_depth - int(
        nullable_collapses_reference_layer(
            type_expr,
            base_is_reference=reference_shape,
        )
    )


__all__ = [
    "const_qualifier_depths",
    "effective_outer_const",
    "effective_outer_volatile",
    "strip_outer_storage_through_typedef",
    "volatile_qualifier_depths",
]
