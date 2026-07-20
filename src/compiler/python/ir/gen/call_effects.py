"""Conservative source-call ownership effects."""

from __future__ import annotations

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    Identifier,
)
from ...ownership_effects import owned_transfer_param_indices


def callable_for_call(gen, node: CallExpr):
    """Resolve the source declaration targeted by ``node`` when possible."""
    callee = node.callee
    if isinstance(callee, FieldAccessExpr):
        from .rich_enum_calls import rich_enum_variant_target

        variant = rich_enum_variant_target(gen, node)
        if variant is not None:
            return variant[1]
        receiver_type = gen.analyzed.node_types.get(id(callee.obj))
        if receiver_type is not None:
            class_info = gen.analyzed.class_table.get(receiver_type.base)
            if class_info is not None:
                method = class_info.methods.get(callee.field)
                if method is not None:
                    return method
        if isinstance(callee.obj, Identifier) and not gen.local_ownership_declared(callee.obj.name):
            class_info = gen.analyzed.class_table.get(callee.obj.name)
            if class_info is not None:
                return class_info.methods.get(callee.field)
        return None

    if not isinstance(callee, Identifier):
        return None
    if gen.local_ownership_declared(callee.name):
        return None
    if id(node) in gen.analyzed.hosted_call_ids:
        return None
    class_info = gen.analyzed.class_table.get(callee.name)
    if class_info is not None:
        return class_info.constructor
    return gen.analyzed.function_table.get(callee.name)


__all__ = ["callable_for_call", "owned_transfer_param_indices"]
