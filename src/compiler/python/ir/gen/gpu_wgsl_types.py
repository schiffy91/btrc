"""Closed btrc-to-WGSL scalar type mapping."""

from __future__ import annotations

from .errors import CodegenError

TYPE_MAP = {
    "int": "i32",
    "float": "f32",
    "bool": "bool",
}


def scalar_type(type_expr) -> str:
    if type_expr is None or type_expr.base not in TYPE_MAP:
        name = "void" if type_expr is None else type_expr.base
        raise CodegenError(f"type '{name}' has no WGSL scalar representation")
    return TYPE_MAP[type_expr.base]


def btrc_type_to_wgsl(type_expr) -> str:
    if type_expr is None:
        return "void"
    scalar = scalar_type(type_expr)
    return f"array<{scalar}>" if type_expr.is_array else scalar


def btrc_type_to_wgsl_elem(type_expr) -> str:
    return scalar_type(type_expr)
