"""Semantics-preserving WGSL expression lowering."""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    CallExpr,
    CastExpr,
    FloatLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    NullLiteral,
    TernaryExpr,
    UnaryExpr,
)
from ...gpu_builtins import WGSL_CALL_BUILTINS
from .errors import unsupported_node
from .gpu_wgsl_checks import WgslChecksMixin
from .gpu_wgsl_types import scalar_type

_DIRECT_BINARY_OPERATORS = frozenset(
    {
        "+",
        "-",
        "*",
        "/",
        "%",
        "==",
        "!=",
        "<",
        ">",
        "<=",
        ">=",
        "&",
        "|",
        "^",
        "<<",
        ">>",
    }
)


class WgslExpressionsMixin(WgslChecksMixin):
    """Expression lowering shared with the statement-oriented emitter."""

    def _expr(self, expression) -> str:
        if isinstance(expression, IntLiteral):
            return str(expression.value)
        if isinstance(expression, FloatLiteral):
            raw = expression.raw or str(expression.value)
            if raw.endswith(("f", "F")):
                raw = raw[:-1]
            if "." not in raw and "e" not in raw.lower():
                raw += ".0"
            return raw
        if isinstance(expression, BoolLiteral):
            return "true" if expression.value else "false"
        if isinstance(expression, NullLiteral):
            raise unsupported_node("WGSL expression", expression)
        if isinstance(expression, Identifier):
            return self._identifier(expression.name)
        if isinstance(expression, BinaryExpr):
            return self._binary_expr(expression)
        if isinstance(expression, UnaryExpr):
            return self._unary_expr(expression)
        if isinstance(expression, CallExpr):
            return self._call_expr(expression)
        if isinstance(expression, IndexExpr):
            return self._checked_index_expr(expression)
        if isinstance(expression, AssignExpr):
            target = self._expr(expression.target)
            target_type = self._type_of(expression.target)
            value = self._coerced_expr(expression.value, target_type)
            if expression.op in ("/=", "%="):
                checked = self._checked_divmod_expr(
                    expression.op[0],
                    target,
                    value,
                    getattr(target_type, "base", "int"),
                )
                return f"{target} = {checked}"
            if expression.op == "^=" and getattr(target_type, "base", None) == "bool":
                return f"{target} = ({target} != {value})"
            if expression.op in ("<<=", ">>="):
                return f"{target} {expression.op} u32({value})"
            return f"{target} {expression.op} {value}"
        if isinstance(expression, TernaryExpr):
            return self._ternary_expr(expression)
        if isinstance(expression, CastExpr):
            return self._cast_expr(expression)
        raise unsupported_node("WGSL expression", expression)

    def _identifier(self, name: str) -> str:
        mapped = self._lookup_name(name)
        if name in self._uniform_params:
            field = self._uniform_params[name]
            if name in self._bool_uniform_params:
                return f"(uniforms.{field} != 0u)"
            return f"uniforms.{field}"
        return mapped

    def _binary_expr(self, expression: BinaryExpr) -> str:
        if expression.op in ("&&", "||"):
            return self._short_circuit_expr(expression)
        if expression.op not in _DIRECT_BINARY_OPERATORS:
            raise unsupported_node("WGSL binary expression", expression)
        left_type = self._type_of(expression.left)
        right_type = self._type_of(expression.right)
        left = self._expr(expression.left)
        right = self._expr(expression.right)
        if expression.op == "^" and left_type is not None and left_type.base == "bool":
            return f"({left} != {right})"
        if _is_mixed_numeric(left_type, right_type):
            left = self._coerce_text(left, left_type, "float")
            right = self._coerce_text(right, right_type, "float")
        if expression.op in ("/", "%"):
            result_base = (
                "float"
                if "float"
                in {
                    getattr(left_type, "base", None),
                    getattr(right_type, "base", None),
                }
                else "int"
            )
            return self._checked_divmod_expr(
                expression.op,
                left,
                right,
                result_base,
            )
        if expression.op in ("<<", ">>"):
            right = f"u32({right})"
        return f"({left} {expression.op} {right})"

    def _short_circuit_expr(self, expression: BinaryExpr) -> str:
        left = self._expr(expression.left)
        temporary = self._fresh_value_name()
        self._line(f"var {temporary}: bool = {left};")
        condition = temporary if expression.op == "&&" else f"!{temporary}"
        self._line(f"if ({condition}) {{")
        self._indent += 1
        right = self._expr(expression.right)
        self._line(f"{temporary} = {right};")
        self._indent -= 1
        self._line("}")
        return temporary

    def _unary_expr(self, expression: UnaryExpr) -> str:
        operand = self._expr(expression.operand)
        if expression.op in ("++", "--"):
            # WGSL only has postfix update statements. GPU validation ensures
            # the value is discarded, so prefix and postfix btrc forms agree.
            operand_type = self._type_of(expression.operand)
            if operand_type is not None and operand_type.base == "float":
                operator = "+=" if expression.op == "++" else "-="
                return f"{operand} {operator} 1.0"
            return f"{operand}{expression.op}"
        if expression.op == "+":
            return operand
        if expression.op in ("!", "~", "-"):
            return f"({expression.op}{operand})"
        raise unsupported_node("WGSL unary expression", expression)

    def _call_expr(self, expression: CallExpr) -> str:
        if not isinstance(expression.callee, Identifier):
            raise unsupported_node("WGSL call expression", expression.callee)
        name = expression.callee.name
        if name == "gpu_id":
            return "btrc_gid"
        if name not in WGSL_CALL_BUILTINS:
            raise unsupported_node("WGSL call expression", expression)
        if name == "round":
            return self._round_away_from_zero(expression.args[0])
        arguments = ", ".join(self._expr(argument) for argument in expression.args)
        return f"{name}({arguments})"

    def _round_away_from_zero(self, argument) -> str:
        value = self._expr(argument)
        temporary = self._fresh_value_name()
        self._line(f"let {temporary}: f32 = {value};")
        away = f"select(ceil({temporary} - 0.5), floor({temporary} + 0.5), {temporary} >= 0.0)"
        # C/BTRC round preserves signed zero and rounds ties away from zero;
        # WGSL's round() uses ties-to-even, so spell the source contract out.
        return f"select({away}, {temporary}, {temporary} == 0.0)"

    def _ternary_expr(self, expression: TernaryExpr) -> str:
        result_type = self._type_of(expression)
        temporary = self._fresh_value_name()
        condition = self._expr(expression.condition)
        self._line(f"var {temporary}: {scalar_type(result_type)};")
        self._line(f"if ({condition}) {{")
        self._indent += 1
        true_value = self._coerced_expr(expression.true_expr, result_type)
        self._line(f"{temporary} = {true_value};")
        self._indent -= 1
        self._line("} else {")
        self._indent += 1
        false_value = self._coerced_expr(expression.false_expr, result_type)
        self._line(f"{temporary} = {false_value};")
        self._indent -= 1
        self._line("}")
        return temporary

    def _cast_expr(self, expression: CastExpr) -> str:
        inner = self._expr(expression.expr)
        source = self._type_of(expression.expr)
        return self._coerce_text(inner, source, expression.target_type.base)

    def _coerced_expr(self, expression, target_type) -> str:
        return self._coerce_text(self._expr(expression), self._type_of(expression), target_type)

    def _coerce_text(self, text: str, source_type, target_type) -> str:
        source = getattr(source_type, "base", source_type)
        target = getattr(target_type, "base", target_type)
        if source is None or target is None or source == target:
            return text
        if source == "bool" and target == "int":
            return f"select(0, 1, {text})"
        if source == "bool" and target == "float":
            return f"select(0.0, 1.0, {text})"
        if target == "bool" and source == "int":
            return f"({text} != 0)"
        if target == "bool" and source == "float":
            return f"({text} != 0.0)"
        if source in ("int", "float") and target in ("int", "float"):
            return f"{scalar_type(_type_with_base(target))}({text})"
        return text


def _is_mixed_numeric(left_type, right_type) -> bool:
    return {getattr(left_type, "base", None), getattr(right_type, "base", None)} == {
        "int",
        "float",
    }


def _type_with_base(base: str):
    from ...ast_nodes import TypeExpr

    return TypeExpr(base=base)
