"""Direct automatic-storage provenance carried by structured IR lvalues."""

from .nodes import IRDeref, IRFieldAccess, IRIndex, IRVar


def direct_storage_root(value: object) -> str | None:
    """Return the automatic object changed by an lvalue, never its pointee.

    Source indexes and synthesized dereferences carry a resolved answer because
    their rendered C shape alone cannot distinguish an array object from a raw
    pointer. Older compiler-authored indexes retain the structural fallback.
    """

    if isinstance(value, IRVar):
        return value.name
    if isinstance(value, IRFieldAccess):
        return None if value.arrow else direct_storage_root(value.obj)
    if isinstance(value, (IRIndex, IRDeref)) and value.storage_root_known:
        return value.storage_root or None
    if isinstance(value, IRIndex):
        return direct_storage_root(value.obj)
    return None


def record_index_storage(index: IRIndex, receiver_type: object | None) -> IRIndex:
    """Annotate a source index with its semantic array-vs-pointer identity."""

    index.storage_root_known = True
    if receiver_type is not None and getattr(receiver_type, "is_array", False):
        index.storage_root = direct_storage_root(index.obj) or ""
    return index


def record_array_projection(field, result_type: object | None):
    """Annotate an array-valued field with its enclosing automatic root."""

    if result_type is not None and getattr(result_type, "is_array", False):
        field.array_storage_known = True
        field.array_storage_root = direct_storage_root(field) or ""
    return field


def record_array_value(value, result_type: object | None):
    """Annotate a bare array-valued binding before C array-to-pointer decay."""

    if result_type is not None and getattr(result_type, "is_array", False):
        value.array_storage_known = True
        value.array_storage_root = direct_storage_root(value) or ""
    return value


__all__ = [
    "direct_storage_root",
    "record_array_projection",
    "record_array_value",
    "record_index_storage",
]
