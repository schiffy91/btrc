"""Evaluation-order policy for managed operands."""

from ...ast_nodes import Identifier
from .evaluation_order import (
    borrowed_value_can_be_pinned,
    has_observable_effect,
    reorder_inert,
)
from .lowering_context import LoweringContext


class OwnershipOperandOrder:
    """Compute stabilization pins and concrete temporary value types."""

    def __init__(self, context: LoweringContext, types) -> None:
        self.context = context
        self.analyzed = context.analyzed
        self.types = types

    def has_effect(self, node) -> bool:
        """Whether evaluating ``node`` can change a later operand."""
        return has_observable_effect(
            self,
            node,
            type_of=self.context.type_of,
        )

    def operands_require_order(self, nodes) -> bool:
        """Whether C's unspecified operand order can change semantics."""
        effects = [self.has_effect(node) for node in nodes]
        for left_index, left in enumerate(nodes):
            for right_index in range(left_index + 1, len(nodes)):
                right = nodes[right_index]
                if effects[left_index] and not reorder_inert(self, right):
                    return True
                if effects[right_index] and not reorder_inert(self, left):
                    return True
        return False

    def source_order_pin_flags(self, nodes, types, owned) -> list[bool]:
        effects = [self.has_effect(node) for node in nodes]
        return [
            bool(
                borrowed_value_can_be_pinned(nodes[index])
                and not owned[index]
                and self.types.is_managed(types[index])
                and any(effects[index + 1 :])
            )
            for index in range(len(nodes))
        ]

    def operand_c_type(self, node, type_expr, *, render):
        if isinstance(node, Identifier) and any(node.name in values for values in self.analyzed.enum_table.values()):
            return "int"
        return render(type_expr)


__all__ = ["OwnershipOperandOrder"]
