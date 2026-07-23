"""Physical-storage and virtual mutation-target contracts."""

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    Identifier,
    IndexExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    TernaryExpr,
    UnaryExpr,
)
from ..source_runtime_symbols import is_source_runtime_helper


class LvalueContractsMixin:
    _MANAGED_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})

    def _is_lvalue(self, expression) -> bool:
        """Whether mutation can write back through this source expression."""
        if isinstance(expression, Identifier):
            return self._identifier_is_storage(expression)
        if isinstance(expression, IndexExpr):
            return self._is_protocol_index_projection(expression) or self._is_addressable_storage(expression)
        if isinstance(expression, UnaryExpr):
            return expression.op == "*"
        if not isinstance(expression, FieldAccessExpr) or expression.optional:
            return False
        if self._is_property_projection(expression):
            return True
        return self._is_addressable_storage(expression)

    def _is_addressable_storage(self, expression) -> bool:
        """Whether an expression denotes physical storage, not a getter copy."""
        if isinstance(expression, Identifier):
            return self._identifier_is_storage(expression)
        if isinstance(expression, UnaryExpr):
            return expression.op == "*"
        if isinstance(expression, IndexExpr):
            if self._is_protocol_index_projection(expression):
                return False
            receiver_type = self._canonical_type(self._infer_type(expression.obj))
            if receiver_type is None:
                return True
            if receiver_type.is_array:
                return self._is_addressable_storage(expression.obj)
            if receiver_type.base == "string" or self._is_raw_pointer_value(receiver_type):
                return True
            return self._is_addressable_storage(expression.obj)
        if not isinstance(expression, FieldAccessExpr) or expression.optional:
            return False
        if self._is_property_projection(expression) or self._is_computed_field_projection(expression):
            return False
        if isinstance(expression.obj, Identifier):
            class_info = self.declarations.class_table.get(expression.obj.name)
            if class_info is not None and expression.field in class_info.static_fields:
                return True
        receiver_type = self._canonical_type(self._infer_type(expression.obj))
        if self._is_reference_receiver(receiver_type):
            return True
        return self._is_addressable_storage(expression.obj)

    def _is_lifetime_stable_storage(self, expression) -> bool:
        return self._is_addressable_storage(expression) and not self._has_temporary_managed_owner(expression)

    def _validate_address_operand(self, expression) -> None:
        operand = expression.operand
        name = getattr(operand, "name", None)
        valid = (
            self._is_lifetime_stable_storage(operand)
            or name in self.declarations.function_table
            or is_source_runtime_helper(name)
        )
        if valid:
            return
        operand_type = self._infer_type(operand)
        spelling = self._format_type(operand_type) if operand_type is not None else "unknown"
        self.context.error(
            f"Unary operator '&' is not defined for '{spelling}'",
            expression.line,
            expression.col,
        )

    def _has_temporary_managed_owner(self, expression) -> bool:
        result_type = self._canonical_type(self._infer_type(expression))
        managed_result = bool(
            result_type
            and (
                result_type.base in self.declarations.class_table
                or result_type.base in self._MANAGED_COLLECTION_BASES
                or result_type.base == "Mutex"
                or self.type_identity.is_scalar_string(result_type)
            )
        )
        if isinstance(expression, (CallExpr, NewExpr)):
            return managed_result
        if isinstance(expression, (ListLiteral, MapLiteral)):
            return True
        if isinstance(expression, BraceInitializer):
            return managed_result
        if isinstance(expression, CastExpr):
            return self._has_temporary_managed_owner(expression.expr)
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, AssignExpr):
            target = expression.target
            return bool(
                managed_result
                and (
                    (isinstance(target, (FieldAccessExpr, IndexExpr)) and self._has_temporary_managed_owner(target.obj))
                    or (
                        expression.op == "="
                        and self._is_virtual_update_target(target)
                        and self._has_temporary_managed_owner(expression.value)
                    )
                )
            )
        if isinstance(expression, BinaryExpr) and expression.op != "??" and managed_result:
            if expression.op == "+" and all(
                self.type_identity.is_scalar_string(self._canonical_type(self._infer_type(operand)))
                for operand in (expression.left, expression.right)
            ):
                return True
            operand_type = self._infer_type(expression.left)
            return self._operator_method(operand_type, expression.op) is not None
        if isinstance(expression, UnaryExpr) and managed_result:
            operand_type = self._infer_type(expression.operand)
            return self._operator_method(operand_type, expression.op, unary=True) is not None
        if isinstance(expression, IndexExpr):
            if managed_result and self._is_protocol_index_projection(expression):
                return True
            return self._has_temporary_managed_owner(expression.obj)
        if isinstance(expression, FieldAccessExpr):
            return self._has_temporary_managed_owner(expression.obj)
        if isinstance(expression, TernaryExpr):
            return self._has_temporary_managed_owner(expression.true_expr) or self._has_temporary_managed_owner(
                expression.false_expr
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._has_temporary_managed_owner(expression.left) or self._has_temporary_managed_owner(
                expression.right
            )
        return False

    def _target_has_const_receiver(self, expression) -> bool:
        if not isinstance(expression, (FieldAccessExpr, IndexExpr)):
            return False
        receiver_type = self._canonical_type(self._infer_type(expression.obj))
        if receiver_type is not None and receiver_type.is_const:
            return True
        if isinstance(expression, IndexExpr) and self._is_raw_pointer_value(receiver_type):
            return False
        return self._target_has_const_receiver(expression.obj)

    def _is_property_projection(self, expression: FieldAccessExpr) -> bool:
        receiver_type = self._canonical_type(self._infer_type(expression.obj))
        class_info = self.declarations.class_table.get(receiver_type.base) if receiver_type else None
        return bool(class_info is not None and expression.field in class_info.properties)

    def _is_computed_field_projection(self, expression: FieldAccessExpr) -> bool:
        receiver_type = self._canonical_type(self._infer_type(expression.obj))
        return bool(receiver_type and receiver_type.base == "string")

    def _is_protocol_index_projection(self, expression: IndexExpr) -> bool:
        receiver_type = self._canonical_type(self._infer_type(expression.obj))
        if receiver_type is None:
            return False
        if receiver_type.is_array or receiver_type.base == "string" or self._is_raw_pointer_value(receiver_type):
            return False
        return self.index_protocols.class_info(receiver_type) is not None

    def _is_virtual_update_target(self, expression) -> bool:
        return (isinstance(expression, FieldAccessExpr) and self._is_property_projection(expression)) or (
            isinstance(expression, IndexExpr) and self._is_protocol_index_projection(expression)
        )

    def _is_reference_receiver(self, type_expr) -> bool:
        return bool(
            type_expr
            and (
                type_expr.pointer_depth > 0
                or type_expr.is_array
                or type_expr.base == "string"
                or type_expr.base == "Mutex"
                or type_expr.base in self.declarations.class_table
            )
        )

    def _identifier_is_storage(self, expression: Identifier) -> bool:
        symbol = self.scope.lookup(expression.name)
        if symbol is not None:
            return symbol.kind != "function"
        if expression.name in self.declarations.function_table:
            return False
        if expression.name in self.declarations.class_table or expression.name in self.declarations.enum_table:
            return False
        if expression.name in self.declarations.rich_enum_table:
            return False
        # Preserve unresolved C-interoperability identifiers; their storage
        # category is intentionally outside the source-language symbol table.
        return not bool(self.declarations.enum_member_owners.get(expression.name))


__all__ = ["LvalueContractsMixin"]
