"""Semantic contracts for operators, assignments, indexing, and ownership."""

from ..ast_nodes import (
    FieldAccessExpr,
)
from ..numeric_semantics import integer_mix_is_portable, is_numeric_type
from ..operator_semantics import (
    OperatorTypeError,
    coalesce_domain,
    comparison_domain,
    is_scalar_string_type,
)


class ExpressionContractsMixin:
    _INTEGRAL_TYPES = frozenset(
        (
            "bool",
            "byte",
            "char",
            "short",
            "short int",
            "int",
            "long",
            "long int",
            "long long",
            "long long int",
            "signed",
            "unsigned",
            "unsigned char",
            "uint",
            "unsigned int",
            "unsigned short",
            "unsigned short int",
            "unsigned long",
            "unsigned long int",
            "unsigned long long",
            "unsigned long long int",
            "signed char",
            "signed short",
            "signed short int",
            "signed int",
            "signed long",
            "signed long int",
            "signed long long",
            "signed long long int",
        )
    )

    def _is_numeric_value(self, type_expr) -> bool:
        type_expr = self._canonical_type(type_expr)
        return (
            bool(
                type_expr
                and type_expr.base in self._NUMERIC_TYPES
                and type_expr.pointer_depth == 0
                and not type_expr.is_array
                and not type_expr.generic_args
            )
            or self._is_opaque_c_scalar(type_expr)
            or self._is_native_enum_scalar(type_expr)
        )

    def _is_integral_value(self, type_expr) -> bool:
        type_expr = self._canonical_type(type_expr)
        return (
            bool(
                type_expr
                and type_expr.base in self._INTEGRAL_TYPES
                and type_expr.pointer_depth == 0
                and not type_expr.is_array
                and not type_expr.generic_args
            )
            or self._is_opaque_c_scalar(type_expr)
            or self._is_native_enum_scalar(type_expr)
        )

    def _is_pointer_value(self, type_expr) -> bool:
        type_expr = self._canonical_type(type_expr)
        return bool(type_expr and (type_expr.pointer_depth > 0 or type_expr.is_array or type_expr.base == "string"))

    def _is_raw_pointer_value(self, type_expr) -> bool:
        type_expr = self._canonical_type(type_expr)
        active_type_param = bool(type_expr and type_expr.base in self._active_storage_type_parameters())
        nominal_reference = bool(
            type_expr
            and not active_type_param
            and (type_expr.base in self.declarations.class_table or type_expr.base in self.declarations.interface_table)
        )
        return bool(
            type_expr
            and (type_expr.pointer_depth > 0 or type_expr.is_array)
            and (type_expr.is_array or not nominal_reference or type_expr.pointer_depth > 1)
        )

    def _validate_binary_expr(self, expression):
        left = self._infer_type(expression.left)
        right = self._infer_type(expression.right)
        if left is None or right is None:
            return
        self._reject_thread_observation(expression.left)
        self._reject_thread_observation(expression.right)
        operator = expression.op
        if left.base == right.base and self._is_active_type_parameter(left):
            return
        overload = self._operator_method(left, operator)
        if overload is not None:
            self._validate_operator_argument(expression, operator, right, overload)
            self._validate_operator_access(left, operator, expression)
            return
        if operator == "+" and is_scalar_string_type(left) and is_scalar_string_type(right):
            return
        if operator in {
            "+",
            "-",
            "*",
            "/",
            "%",
            "&",
            "|",
            "^",
            "<<",
            ">>",
            "==",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
        } and not self._validate_portable_numeric_mix(
            expression,
            left,
            right,
            f"Operator '{operator}'",
        ):
            return
        if operator == "??":
            try:
                coalesce_domain(
                    self._canonical_type(left),
                    self._canonical_type(right),
                    left_is_optional_value=(isinstance(expression.left, FieldAccessExpr) and expression.left.optional),
                    class_table=self.declarations.class_table,
                    interface_table=self.declarations.interface_table,
                    enum_names=frozenset(self.declarations.enum_table),
                )
            except OperatorTypeError as error:
                self._error(str(error), expression.line, expression.col)
            return
        if operator in ("&&", "||"):
            valid = left.base == right.base == "bool"
        elif operator in ("&", "|", "^", "<<", ">>"):
            valid = self._is_integral_value(left) and self._is_integral_value(right)
        elif operator in ("+", "-"):
            numeric = self._is_numeric_value(left) and self._is_numeric_value(right)
            pointer_offset = (self._is_raw_pointer_value(left) and self._is_integral_value(right)) or (
                operator == "+" and self._is_integral_value(left) and self._is_raw_pointer_value(right)
            )
            pointer_difference = (
                operator == "-"
                and self._is_raw_pointer_value(left)
                and self._is_raw_pointer_value(right)
                and (self._types_compatible(left, right) or self._types_compatible(right, left))
            )
            valid = numeric or pointer_offset or pointer_difference
        elif operator in ("*", "/", "%"):
            valid = self._is_numeric_value(left) and self._is_numeric_value(right)
        elif operator in ("==", "!=", "<", ">", "<=", ">="):
            try:
                comparison_domain(
                    operator,
                    self._canonical_type(left),
                    self._canonical_type(right),
                    class_table=self.declarations.class_table,
                    interface_table=self.declarations.interface_table,
                    enum_names=frozenset(self.declarations.enum_table),
                )
            except OperatorTypeError as error:
                self._error(str(error), expression.line, expression.col)
            return
        else:
            return
        if not valid:
            self._error(
                f"Operator '{operator}' is not defined for "
                f"'{self._format_type(left)}' and '{self._format_type(right)}'",
                expression.line,
                expression.col,
            )

    def _validate_ternary_expr(self, expression):
        true_type = self._infer_type(expression.true_expr)
        false_type = self._infer_type(expression.false_expr)
        if (
            true_type
            and false_type
            and not self._validate_portable_numeric_mix(
                expression,
                true_type,
                false_type,
                "Ternary expression",
            )
        ):
            return
        if (
            true_type
            and false_type
            and not self._types_compatible(true_type, false_type)
            and not self._types_compatible(false_type, true_type)
        ):
            self._error(
                "Ternary branches have incompatible types "
                f"'{self._format_type(true_type)}' and "
                f"'{self._format_type(false_type)}'",
                expression.line,
                expression.col,
            )

    def _validate_portable_numeric_mix(
        self,
        expression,
        left,
        right,
        context,
    ) -> bool:
        left = self._canonical_type(left)
        right = self._canonical_type(right)
        enum_names = frozenset(self.declarations.enum_table)
        if not (is_numeric_type(left, enum_names) and is_numeric_type(right, enum_names)) or integer_mix_is_portable(
            left, right
        ):
            return True
        self._error(
            f"{context} mixes ABI-dependent integer type "
            f"'{self._format_type(left)}' with '{self._format_type(right)}'; "
            "cast explicitly to a fixed-width or built-in integer type",
            expression.line,
            expression.col,
        )
        return False
