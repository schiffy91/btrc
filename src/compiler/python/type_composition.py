"""Nullable-boundary-preserving composition of source type shapes."""

from dataclasses import replace

from .ast_nodes import TypeExpr

_INTRINSIC_REFERENCE_BASES = frozenset(
    {"Array", "List", "Map", "Mutex", "Set", "Thread", "Vector", "__fn_ptr", "string"}
)


def resolved_reference_shape(type_expr: TypeExpr) -> bool:
    return bool(type_expr.pointer_depth > 0 or type_expr.is_array or type_expr.base in _INTRINSIC_REFERENCE_BASES)


def nullable_collapses_reference_layer(
    type_expr: TypeExpr,
    *,
    base_is_reference: bool = False,
) -> bool:
    """Whether ``?`` annotates an inner reference instead of adding C storage."""
    if not type_expr.is_nullable or type_expr.pointer_depth <= 0:
        return False
    inner_storage = type_expr.pointer_depth + int(type_expr.is_array) - type_expr.nullable_outer_depth
    return inner_storage > 1 or (base_is_reference and inner_storage > 0)


def compose_type_expr(
    applied: TypeExpr,
    resolved: TypeExpr,
    *,
    reference_shape: TypeExpr | None = None,
) -> TypeExpr:
    """Apply one source type shell without losing a resolved nullable boundary."""
    reference_shape = reference_shape or resolved
    collapse_applied = nullable_collapses_reference_layer(
        applied,
        base_is_reference=resolved_reference_shape(reference_shape),
    )
    applied_pointer_depth = applied.pointer_depth - int(collapse_applied)
    surviving_shell_storage = applied_pointer_depth + int(applied.is_array)
    if resolved.is_nullable:
        nullable_outer_depth = resolved.nullable_outer_depth + surviving_shell_storage
    elif applied.is_nullable:
        nullable_outer_depth = surviving_shell_storage if collapse_applied else applied.nullable_outer_depth
    else:
        nullable_outer_depth = 0
    return replace(
        resolved,
        pointer_depth=resolved.pointer_depth + applied_pointer_depth,
        is_array=applied.is_array or resolved.is_array,
        array_size=applied.array_size if applied.array_size is not None else resolved.array_size,
        is_const=applied.is_const or resolved.is_const,
        is_nullable=applied.is_nullable or resolved.is_nullable,
        nullable_outer_depth=nullable_outer_depth,
        is_static=applied.is_static or resolved.is_static,
        is_extern=applied.is_extern or resolved.is_extern,
        is_volatile=applied.is_volatile or resolved.is_volatile,
        line=applied.line or resolved.line,
        col=applied.col or resolved.col,
    )


def strip_outer_storage(type_expr: TypeExpr, *, array: bool = False) -> TypeExpr:
    """Remove one outer pointer/array layer and its nullable provenance."""
    changes = {}
    if array:
        changes.update(is_array=False, array_size=None)
    else:
        changes["pointer_depth"] = type_expr.pointer_depth - 1
    if type_expr.nullable_outer_depth > 0:
        changes["nullable_outer_depth"] = type_expr.nullable_outer_depth - 1
    elif type_expr.is_nullable:
        inner_storage = type_expr.pointer_depth + int(type_expr.is_array) - type_expr.nullable_outer_depth
        changes.update(is_nullable=False, nullable_outer_depth=0)
        if inner_storage > 1:
            changes["pointer_depth"] = changes.get("pointer_depth", type_expr.pointer_depth) - 1
    result = replace(type_expr, **changes)
    if result.is_nullable and result.nullable_outer_depth == 0 and result.pointer_depth + int(result.is_array) == 0:
        result = replace(result, is_nullable=False)
    return result


def add_outer_pointer(type_expr: TypeExpr, *, clear_array: bool = False) -> TypeExpr:
    """Add address-of storage outside any preserved nullable marker."""
    result = strip_outer_storage(type_expr, array=True) if clear_array and type_expr.is_array else type_expr
    return replace(
        result,
        pointer_depth=result.pointer_depth + 1,
        nullable_outer_depth=result.nullable_outer_depth + int(result.is_nullable),
    )


__all__ = [
    "add_outer_pointer",
    "compose_type_expr",
    "nullable_collapses_reference_layer",
    "resolved_reference_shape",
    "strip_outer_storage",
]
