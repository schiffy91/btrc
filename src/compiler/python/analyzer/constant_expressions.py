"""Recognition and partial evaluation of C integer constant expressions."""

from ..ast_nodes import (
    BinaryExpr,
    BoolLiteral,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    Identifier,
    IntLiteral,
    SizeofExpr,
    TernaryExpr,
    UnaryExpr,
)
from ..numeric_literals import (
    convert_integral_constant,
    decode_character_constant,
)


class ConstantExpressionMixin:
    def _integer_constant_expression(
        self,
        expression,
        *,
        enum_owner=None,
        allowed_enum_members=(),
    ) -> tuple[bool, int | None]:
        allowed = frozenset(allowed_enum_members)
        return self._integer_constant_node(expression, enum_owner, allowed)

    def _integer_constant_node(self, expression, enum_owner, allowed):
        if isinstance(expression, IntLiteral):
            return True, expression.value
        if isinstance(expression, BoolLiteral):
            return True, int(expression.value)
        if isinstance(expression, CharLiteral):
            return True, self._character_constant_value(expression.value)
        if isinstance(expression, Identifier):
            return self._constant_identifier(expression.name, enum_owner, allowed)
        if isinstance(expression, FieldAccessExpr):
            return self._constant_field(expression, enum_owner, allowed)
        if isinstance(expression, SizeofExpr):
            return True, None
        if isinstance(expression, CastExpr):
            if not self._is_integral_value(expression.target_type):
                return False, None
            target = self._canonical_type(expression.target_type)
            if target is None:
                return False, None
            if isinstance(expression.expr, FloatLiteral):
                return True, convert_integral_constant(
                    expression.expr.value,
                    target.base,
                )
            valid, value = self._integer_constant_node(
                expression.expr,
                enum_owner,
                allowed,
            )
            if not valid or value is None:
                return valid, value
            return True, convert_integral_constant(value, target.base)
        if isinstance(expression, UnaryExpr) and expression.op in {"+", "-", "~", "!"}:
            valid, value = self._integer_constant_node(expression.operand, enum_owner, allowed)
            if not valid or value is None:
                return valid, None
            return True, self._apply_constant_unary(expression.op, value)
        if isinstance(expression, BinaryExpr):
            if expression.op not in {
                "+",
                "-",
                "*",
                "/",
                "%",
                "<<",
                ">>",
                "&",
                "|",
                "^",
                "==",
                "!=",
                "<",
                ">",
                "<=",
                ">=",
                "&&",
                "||",
            }:
                return False, None
            left_valid, left = self._integer_constant_node(expression.left, enum_owner, allowed)
            right_valid, right = self._integer_constant_node(expression.right, enum_owner, allowed)
            if not left_valid or not right_valid:
                return False, None
            if left is None or right is None:
                return True, None
            return self._apply_constant_binary(expression.op, left, right)
        if isinstance(expression, TernaryExpr):
            condition_valid, condition = self._integer_constant_node(
                expression.condition,
                enum_owner,
                allowed,
            )
            true_valid, true_value = self._integer_constant_node(
                expression.true_expr,
                enum_owner,
                allowed,
            )
            false_valid, false_value = self._integer_constant_node(
                expression.false_expr,
                enum_owner,
                allowed,
            )
            if not condition_valid or not true_valid or not false_valid:
                return False, None
            if condition is not None:
                return True, true_value if condition else false_value
            if true_value == false_value:
                return True, true_value
            return True, None
        return False, None

    def _constant_identifier(self, name, enum_owner, allowed):
        if enum_owner is not None:
            if name in allowed:
                return True, self._enum_constant_values.get((enum_owner, name))
            if name in self.enum_table.get(enum_owner, ()):
                return False, None
            if self._is_constant_macro_name(name):
                return True, None
            return False, None
        owners = self._enum_member_owners.get(name, set())
        if len(owners) == 1:
            owner = next(iter(owners))
            return True, self._enum_constant_values.get((owner, name))
        if self._is_constant_macro_name(name):
            return True, None
        return False, None

    def _constant_field(self, expression, enum_owner, allowed):
        if not isinstance(expression.obj, Identifier):
            return False, None
        owner = expression.obj.name
        values = self.enum_table.get(owner)
        if values is None or expression.field not in values:
            return False, None
        if enum_owner is not None and (owner != enum_owner or expression.field not in allowed):
            return False, None
        return True, self._enum_constant_values.get((owner, expression.field))

    def _is_constant_macro_name(self, name) -> bool:
        return name in self._source_macro_names or (name.isupper() and name != "NULL")

    @staticmethod
    def _character_constant_value(raw):
        return decode_character_constant(raw)

    @staticmethod
    def _apply_constant_unary(operator, value):
        return {"+": lambda: value, "-": lambda: -value, "~": lambda: ~value, "!": lambda: int(not value)}[operator]()

    @staticmethod
    def _apply_constant_binary(operator, left, right):
        if operator in {"/", "%"} and right == 0:
            return False, None
        # btrc currently lowers all un-suffixed integral constants through a
        # 64-bit host domain.  Reject counts outside that domain rather than
        # allowing Python's unbounded shifts to bless undefined strict-C.
        if operator in {"<<", ">>"} and not 0 <= right < 64:
            return False, None
        if operator == "/":
            quotient = abs(left) // abs(right)
            value = -quotient if (left < 0) != (right < 0) else quotient
            return True, value
        if operator == "%":
            _, quotient = ConstantExpressionMixin._apply_constant_binary("/", left, right)
            return True, left - quotient * right
        operations = {
            "+": lambda: left + right,
            "-": lambda: left - right,
            "*": lambda: left * right,
            "<<": lambda: left << right,
            ">>": lambda: left >> right,
            "&": lambda: left & right,
            "|": lambda: left | right,
            "^": lambda: left ^ right,
            "==": lambda: int(left == right),
            "!=": lambda: int(left != right),
            "<": lambda: int(left < right),
            ">": lambda: int(left > right),
            "<=": lambda: int(left <= right),
            ">=": lambda: int(left >= right),
            "&&": lambda: int(bool(left) and bool(right)),
            "||": lambda: int(bool(left) or bool(right)),
        }
        try:
            return True, operations[operator]()
        except (KeyError, OverflowError):
            return False, None


__all__ = ["ConstantExpressionMixin"]
