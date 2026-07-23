"""Scalar, pointer-arithmetic, and collection-literal type inference."""

from dataclasses import replace

from ..ast_nodes import TypeExpr
from ..numeric_semantics import numeric_result_type


class ScalarInferenceMixin:
    def _infer_binary_type(self, expression):
        left = self._infer_type(expression.left)
        right = self._infer_type(expression.right)
        overloaded = self._operator_return_type(left, expression.op)
        if overloaded is not None:
            return overloaded
        if expression.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
            return TypeExpr(base="bool")
        if left and right:
            pointer_result = self._infer_pointer_arithmetic(expression.op, left, right)
            if pointer_result:
                return pointer_result
            numeric = numeric_result_type(
                self._canonical_type(left),
                self._canonical_type(right),
                frozenset(self.declarations.enum_table),
            )
            if numeric is not None:
                return numeric
        return left or right

    def _infer_pointer_arithmetic(self, operator, left, right):
        if operator == "-" and self._is_raw_pointer_value(left):
            if self._is_raw_pointer_value(right):
                return TypeExpr(base="long")
            return left
        if operator == "+":
            if self._is_raw_pointer_value(left):
                return left
            if self._is_raw_pointer_value(right):
                return right
        return None

    def _infer_ternary_type(self, expression):
        true_type = self._infer_type(expression.true_expr)
        false_type = self._infer_type(expression.false_expr)
        if true_type is None or false_type is None:
            return true_type or false_type
        true_is_null = true_type.base == "void" and true_type.pointer_depth > 0 and true_type.is_nullable
        false_is_null = false_type.base == "void" and false_type.pointer_depth > 0 and false_type.is_nullable
        if true_is_null and self._is_pointer_value(false_type):
            return replace(false_type, is_nullable=True)
        if false_is_null and self._is_pointer_value(true_type):
            return replace(true_type, is_nullable=True)
        numeric = numeric_result_type(
            self._canonical_type(true_type),
            self._canonical_type(false_type),
            frozenset(self.declarations.enum_table),
        )
        if numeric is not None:
            return numeric
        if self._types_compatible(true_type, false_type):
            return true_type
        if self._types_compatible(false_type, true_type):
            return false_type
        return true_type

    def _infer_integer_literal_type(self, raw: str, value: int) -> TypeExpr:
        return TypeExpr(base=self.numeric_literals.integer_type(raw, value))

    def _collection_literal_type(self, base, generic_args):
        return TypeExpr(
            base=base,
            generic_args=generic_args,
            pointer_depth=1 if base in self.declarations.class_table else 0,
        )
