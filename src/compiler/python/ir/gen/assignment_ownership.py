"""Ownership provenance for assignment expressions with virtual targets."""

from ...ast_nodes import FieldAccessExpr, IndexExpr, SelfExpr
from ...class_storage import property_needs_backing
from ...index_protocol import indexed_protocol_info


def virtual_assignment_target(gen, target) -> bool:
    """Whether a setter call preserves the RHS +1 as the expression result."""
    if isinstance(target, IndexExpr):
        receiver_type = gen.analyzed.node_types.get(id(target.obj))
        return indexed_protocol_info(
            receiver_type,
            gen.analyzed.class_table,
            method="set",
        ) is not None
    if not isinstance(target, FieldAccessExpr):
        return False
    receiver_type = gen.analyzed.node_types.get(id(target.obj))
    class_info = gen.analyzed.class_table.get(receiver_type.base) if receiver_type else None
    prop = class_info.properties.get(target.field) if class_info else None
    if prop is None:
        return False
    return not (
        isinstance(target.obj, SelfExpr)
        and gen.current_property_backing == target.field
        and property_needs_backing(prop)
    )


__all__ = ["virtual_assignment_target"]
