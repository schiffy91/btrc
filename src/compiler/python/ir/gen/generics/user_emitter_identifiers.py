"""Identifier references in monomorphized generic bodies."""

from ...nodes import IRVar
from ...storage_provenance import record_array_value


def generic_identifier_reference(emitter, expression, c_name):
    """Build one C binding reference with array-decay provenance."""

    return record_array_value(
        IRVar(name=c_name),
        emitter._resolve_expr_type(expression),
    )


__all__ = ["generic_identifier_reference"]
