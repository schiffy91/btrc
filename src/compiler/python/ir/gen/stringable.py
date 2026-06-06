"""Implicit conversion for class values with toString() into string contexts."""

from __future__ import annotations

from ..nodes import IRCall, IRExpr
from .types import mangle_generic_type


def has_to_string(analyzed, source_type) -> bool:
    if not source_type or source_type.base not in analyzed.class_table:
        return False
    method = analyzed.class_table[source_type.base].methods.get("toString")
    if not method or method.params:
        return False
    return method.return_type and method.return_type.base == "string"


def to_string_call(gen, source_type, value: IRExpr) -> IRExpr:
    cls = gen.analyzed.class_table[source_type.base]
    if source_type.generic_args and cls.generic_params:
        prefix = mangle_generic_type(source_type.base, source_type.generic_args)
    else:
        prefix = source_type.base
    return IRCall(callee=f"{prefix}_toString", args=[value])


def coerce_to_string_param(gen, target_type, source_node, value: IRExpr) -> IRExpr:
    if not target_type or target_type.base != "string":
        return value
    source_type = gen.analyzed.node_types.get(id(source_node))
    if has_to_string(gen.analyzed, source_type):
        return to_string_call(gen, source_type, value)
    return value


def coerce_value_to_string(gen, target_type, source_type, value: IRExpr) -> IRExpr:
    if not target_type or target_type.base != "string":
        return value
    if has_to_string(gen.analyzed, source_type):
        return to_string_call(gen, source_type, value)
    return value
