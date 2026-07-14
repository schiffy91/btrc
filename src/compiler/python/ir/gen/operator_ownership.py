"""Ownership metadata for source operator methods."""

from __future__ import annotations


def operator_rhs_keep(gen, left_type, operator: str, right_type) -> bool:
    """Whether an overloaded operator's RHS needs a call-duration keep."""
    from .managed_values import is_managed_type

    if not is_managed_type(gen, right_type) or left_type is None:
        return False
    magic = {
        "+": "__add__",
        "-": "__sub__",
        "*": "__mul__",
        "/": "__div__",
        "%": "__mod__",
        "==": "__eq__",
        "!=": "__ne__",
        "<": "__lt__",
        ">": "__gt__",
        "<=": "__le__",
        ">=": "__ge__",
    }.get(operator)
    class_info = gen.analyzed.class_table.get(left_type.base)
    method = class_info.methods.get(magic) if class_info is not None and magic else None
    return bool(method is not None and method.params and method.params[0].keep)


__all__ = ["operator_rhs_keep"]
