"""Shared recognition of class-backed indexed get/set protocols."""


def indexed_protocol_info(type_expr, class_table, *, method: str | None = None):
    """Return the direct class instance implementing an indexed protocol."""
    if type_expr is None or type_expr.is_array or type_expr.pointer_depth > 1:
        return None
    info = class_table.get(type_expr.base)
    if info is None:
        return None
    if method is not None:
        return info if method in info.methods else None
    return info if {"get", "set"} & info.methods.keys() else None


__all__ = ["indexed_protocol_info"]
