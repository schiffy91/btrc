"""Implicit conversion for class values with toString() into string contexts."""

from __future__ import annotations

from ..nodes import IRCall, IRExpr


def has_to_string(analyzed, source_type) -> bool:
    from ...string_conversion import has_scalar_to_string
    from .type_resolution import canonical_type

    return has_scalar_to_string(
        analyzed.class_table,
        source_type,
        canonicalize=lambda value: canonical_type(
            value,
            analyzed.typedef_table,
        ),
    )


def to_string_call(gen, source_type, value: IRExpr) -> IRExpr:
    cls = gen.analyzed.class_table[source_type.base]
    if source_type.generic_args and cls.generic_params:
        prefix = gen.type_identity.specialization_symbol(source_type.base, source_type.generic_args)
    else:
        prefix = source_type.base
    return IRCall(callee=f"{prefix}_toString", args=[value])
