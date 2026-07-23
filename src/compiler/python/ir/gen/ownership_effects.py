"""Ownership effects supplied by calls and assignment lowering."""

from __future__ import annotations

from ...ast_nodes import FieldAccessExpr, Identifier, IndexExpr, SelfExpr
from ...class_storage import property_needs_backing
from ...string_conversion import requires_class_to_string
from .assignment_ownership import (
    assignment_target_operands,
    kept_target_operands,
    property_projection,
)
from .callable_provenance import (
    AMBIGUOUS_RETURN,
    OWNED_RETURN,
    callable_return_abi,
)
from .errors import CodegenError
from .lowering_context import LoweringContext
from .type_resolution import canonical_type


class OwnershipEffectResolver:
    """Resolve non-local ownership decisions from explicit lowering state."""

    def __init__(self, context: LoweringContext, types, ownership) -> None:
        self.context = context
        self.types = types
        self.ownership = ownership

    def call_returns_owned(self, expression) -> bool:
        """Whether a call is proven to use btrc's caller-owned ABI."""
        analyzed = self.context.analyzed
        callee = expression.callee
        if isinstance(callee, Identifier) and id(expression) in analyzed.hosted_call_ids:
            return False
        return_abi = callable_return_abi(self.context, callee)
        if return_abi == AMBIGUOUS_RETURN:
            raise CodegenError(
                "Managed-return __fn_ptr call has ambiguous ownership ABI after "
                "control flow; keep source and foreign callbacks in separate bindings"
            )
        if return_abi == OWNED_RETURN:
            return True
        if isinstance(callee, Identifier):
            if self._local_is_declared(callee.name):
                return False
            return (
                callee.name == "Mutex" and callee.name not in analyzed.function_table
            ) or callee.name in analyzed.class_table
        if not isinstance(callee, FieldAccessExpr):
            return False

        receiver = callee.obj
        if isinstance(receiver, Identifier):
            static_info = analyzed.class_table.get(receiver.name)
            if static_info is not None:
                static_method = static_info.methods.get(callee.field)
                if static_method is not None:
                    return bool(static_method.body is not None)
        receiver_type = self.context.type_of(receiver)
        receiver_type = self.types.canonical(receiver_type)
        if receiver_type is None:
            return False
        if receiver_type.base == "Thread" and callee.field == "join":
            return True
        if receiver_type.base == "Mutex" and callee.field == "get":
            return True
        class_info = analyzed.class_table.get(receiver_type.base)
        if class_info is not None and callee.field in class_info.methods:
            return True
        interface_info = getattr(analyzed, "interface_table", {}).get(receiver_type.base)
        return bool(interface_info is not None and callee.field in interface_info.methods)

    def assignment_pins_borrowed_target(self, target) -> bool:
        """Whether target evaluation promotes a borrowed managed receiver."""
        operands = assignment_target_operands(
            target,
            stabilize_receiver=lambda receiver: bool(
                self.ownership.owns_result(receiver)
                or self.types.is_managed(self.context.type_of(receiver))
                or property_projection(
                    receiver,
                    type_of=self.context.type_of,
                    class_table=self.context.analyzed.class_table,
                )
            ),
        )
        return bool(
            kept_target_operands(
                target,
                operands,
                type_of=self.context.type_of,
                is_managed=self.types.is_managed,
                owns=self.ownership.owns_result,
            )
        )

    def virtual_assignment_owns(
        self,
        target,
        value,
    ) -> bool:
        """Whether setter lowering preserves the RHS as an owned result."""
        if not self._virtual_assignment_target(target):
            return False
        if self.types.is_managed(self.context.type_of(target)) or self.ownership.owns_result(value):
            return True
        target_type = canonical_type(
            self.context.type_of(target),
            self.context.analyzed.typedef_table,
        )
        source_type = canonical_type(
            self.context.type_of(value),
            self.context.analyzed.typedef_table,
        )
        return requires_class_to_string(
            self.context.analyzed.class_table,
            target_type,
            source_type,
            canonicalize=lambda item: canonical_type(
                item,
                self.context.analyzed.typedef_table,
            ),
        )

    def _virtual_assignment_target(self, target) -> bool:
        if isinstance(target, IndexExpr):
            return (
                self.ownership.index_protocols.class_info(
                    self.context.type_of(target.obj),
                    method="set",
                )
                is not None
            )
        if not isinstance(target, FieldAccessExpr):
            return False
        receiver_type = self.context.type_of(target.obj)
        class_info = self.context.analyzed.class_table.get(receiver_type.base) if receiver_type else None
        prop = class_info.properties.get(target.field) if class_info else None
        if prop is None:
            return False
        return not (
            isinstance(target.obj, SelfExpr)
            and self.context.current_property_backing == target.field
            and property_needs_backing(prop)
        )

    def _local_is_declared(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self.context.local_ownership_scopes))


__all__ = ["OwnershipEffectResolver"]
