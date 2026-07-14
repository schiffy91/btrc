"""Recognition of strict-C constant initializers for static storage."""

from ..ast_nodes import (
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CastExpr,
    FieldAccessExpr,
    FloatLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    ListLiteral,
    NullLiteral,
    StringLiteral,
    TernaryExpr,
    UnaryExpr,
)


class StorageInitializerContractsMixin:
    def _is_static_storage_initializer(self, expression, expected=None) -> bool:
        if isinstance(expression, BraceInitializer):
            return all(self._is_static_storage_initializer(item) for item in expression.elements)
        if isinstance(expression, ListLiteral):
            return bool(expected and expected.is_array) and all(
                self._is_static_storage_initializer(item) for item in expression.elements
            )
        return self._static_initializer_category(expression) is not None

    def _static_initializer_category(self, expression):
        """Return ``integer``, ``arithmetic``, or ``address`` when valid."""
        valid, _ = self._integer_constant_expression(expression)
        if valid:
            return "integer"
        if isinstance(expression, FloatLiteral):
            return "arithmetic"
        if isinstance(expression, StringLiteral):
            return "address"
        if isinstance(expression, NullLiteral):
            return "address"
        if isinstance(expression, Identifier):
            if expression.name in self.function_table:
                return "address"
            symbol = self.global_scope.symbols.get(expression.name)
            if symbol and symbol.type and symbol.type.is_array:
                return "address"
            return None
        if isinstance(expression, UnaryExpr):
            if expression.op == "&" and self._is_static_address_operand(expression.operand):
                return "address"
            if expression.op in {"+", "-"}:
                category = self._static_initializer_category(expression.operand)
                if category == "arithmetic":
                    return category
            return None
        if isinstance(expression, BinaryExpr):
            return self._static_binary_category(expression)
        if isinstance(expression, TernaryExpr):
            return self._static_ternary_category(expression)
        if isinstance(expression, CastExpr):
            return self._static_cast_category(expression)
        return None

    def _static_binary_category(self, expression):
        left = self._static_initializer_category(expression.left)
        right = self._static_initializer_category(expression.right)
        if expression.op == "+" and {left, right} == {"address", "integer"}:
            return "address"
        if expression.op == "-" and left == "address" and right == "integer":
            return "address"
        if left in {"integer", "arithmetic"} and right in {
            "integer",
            "arithmetic",
        }:
            if expression.op in {"+", "-", "*", "/", "<", ">", "<=", ">=", "==", "!="}:
                if expression.op == "/" and self._is_known_numeric_zero(expression.right):
                    return None
                return "integer" if expression.op in {"<", ">", "<=", ">=", "==", "!="} else "arithmetic"
        return None

    def _static_ternary_category(self, expression):
        condition_valid, condition = self._integer_constant_expression(expression.condition)
        if not condition_valid:
            return None
        if condition is not None:
            selected = expression.true_expr if condition else expression.false_expr
            return self._static_initializer_category(selected)
        true_category = self._static_initializer_category(expression.true_expr)
        false_category = self._static_initializer_category(expression.false_expr)
        return true_category if true_category == false_category else None

    def _static_cast_category(self, expression):
        operand = self._static_initializer_category(expression.expr)
        target = self._canonical_type(expression.target_type)
        if target is None or operand is None:
            return None
        if self._is_pointer_value(target):
            return "address" if operand in {"integer", "address"} else None
        if self._is_numeric_value(target):
            if operand not in {"integer", "arithmetic"}:
                return None
            return "integer" if self._is_integral_value(target) else "arithmetic"
        return None

    def _is_static_address_operand(self, expression) -> bool:
        if isinstance(expression, Identifier):
            return bool(expression.name in self.function_table or expression.name in self.global_scope.symbols)
        if isinstance(expression, FieldAccessExpr):
            if expression.arrow:
                return False
            if isinstance(expression.obj, Identifier):
                owner = self.class_table.get(expression.obj.name)
                if owner and expression.field in owner.static_fields:
                    return True
            return self._is_static_address_operand(expression.obj)
        if isinstance(expression, IndexExpr):
            valid_index, _ = self._integer_constant_expression(expression.index)
            return valid_index and self._is_static_array_designator(expression.obj)
        return isinstance(expression, StringLiteral)

    def _is_static_array_designator(self, expression) -> bool:
        if isinstance(expression, StringLiteral):
            return True
        if isinstance(expression, Identifier):
            symbol = self.global_scope.symbols.get(expression.name)
            return bool(symbol and symbol.type and symbol.type.is_array)
        if isinstance(expression, FieldAccessExpr) and not expression.arrow:
            field_type = self._infer_type(expression)
            return bool(field_type and field_type.is_array and self._is_static_address_operand(expression))
        return False

    @staticmethod
    def _is_known_numeric_zero(expression) -> bool:
        return isinstance(expression, (IntLiteral, FloatLiteral, BoolLiteral)) and not expression.value


__all__ = ["StorageInitializerContractsMixin"]
