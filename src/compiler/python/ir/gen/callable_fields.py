"""Function-pointer field queries for call lowering."""

from __future__ import annotations

from ...ast_nodes import FieldAccessExpr, Identifier
from .type_resolution import (
    canonical_type,
    function_pointer_signature,
    substitute_concrete_type,
)


def callable_field_signature(gen, callee: FieldAccessExpr):
    """Return a callable field/property signature, including typedef aliases."""
    analyzed = gen.analyzed
    signature = function_pointer_signature(
        analyzed.node_types.get(id(callee)),
        analyzed.typedef_table,
    )
    if signature is not None:
        return signature

    if isinstance(callee.obj, Identifier):
        owner = analyzed.class_table.get(callee.obj.name)
        if owner is not None and not gen.local_ownership_declared(callee.obj.name):
            member = owner.static_fields.get(callee.field)
            return function_pointer_signature(
                member.type if member else None,
                analyzed.typedef_table,
            )

    receiver = canonical_type(
        analyzed.node_types.get(id(callee.obj)),
        analyzed.typedef_table,
    )
    if receiver is None:
        return None
    owner = analyzed.class_table.get(receiver.base)
    if owner is None:
        return None
    member = owner.fields.get(callee.field) or owner.properties.get(callee.field)
    if member is None:
        return None
    member_type = member.type
    if owner.generic_params and receiver.generic_args:
        member_type = substitute_concrete_type(
            member_type,
            dict(zip(owner.generic_params, receiver.generic_args)),
            analyzed.typedef_table,
            gen.type_identity,
        )
    return function_pointer_signature(member_type, analyzed.typedef_table)


__all__ = ["callable_field_signature"]
