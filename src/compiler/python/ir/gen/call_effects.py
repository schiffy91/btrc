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
        receiver_type = gen.analyzed.node_types.get(id(callee.obj))
        if receiver_type is not None:
            class_info = gen.analyzed.class_table.get(receiver_type.base)
            if class_info is not None:
                method = class_info.methods.get(callee.field)
                if method is not None:
                    return method
        if isinstance(callee.obj, Identifier):
            class_info = gen.analyzed.class_table.get(callee.obj.name)
            if class_info is not None:
                return class_info.methods.get(callee.field)
        return None

    if not isinstance(callee, Identifier):
        return None
    class_info = gen.analyzed.class_table.get(callee.name)
    if class_info is not None:
        return class_info.constructor
    return gen.analyzed.function_table.get(callee.name)


__all__ = ["callable_for_call", "owned_transfer_param_indices"]
