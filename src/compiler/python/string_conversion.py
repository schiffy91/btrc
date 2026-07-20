"""Pure semantic shape checks for implicit class-to-string conversion."""

from collections.abc import Callable


def is_scalar_string(type_expr) -> bool:
    """Whether a type is exactly the language's scalar string value."""
    return bool(
        type_expr
        and type_expr.base == "string"
        and type_expr.pointer_depth == 0
        and not type_expr.is_array
        and not type_expr.generic_args
    )


def has_scalar_to_string(
    class_table,
    source_type,
    *,
    canonicalize: Callable | None = None,
) -> bool:
    """Whether a semantic class reference provides scalar toString()."""
    if canonicalize is not None:
        source_type = canonicalize(source_type)
    if (
        source_type is None
        or source_type.base not in class_table
        or source_type.pointer_depth != 1
        or source_type.is_array
    ):
        return False
    method = class_table[source_type.base].methods.get("toString")
    return_type = method.return_type if method is not None else None
    if canonicalize is not None:
        return_type = canonicalize(return_type)
    return bool(method and not method.params and is_scalar_string(return_type))


def requires_class_to_string(
    class_table,
    target_type,
    source_type,
    *,
    canonicalize: Callable | None = None,
) -> bool:
    """Whether these exact source/target shapes require runtime conversion."""
    if canonicalize is not None:
        target_type = canonicalize(target_type)
    return is_scalar_string(target_type) and has_scalar_to_string(
        class_table,
        source_type,
        canonicalize=canonicalize,
    )


__all__ = [
    "has_scalar_to_string",
    "is_scalar_string",
    "requires_class_to_string",
]
