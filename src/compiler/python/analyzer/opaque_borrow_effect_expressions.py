"""Expression provenance for conservative opaque-borrow effect proofs."""

from ..ast_nodes import (
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    TernaryExpr,
    TupleLiteral,
    UnaryExpr,
)
from ..hosted_abi import hosted_return_alias_parameter
from .opaque_borrow_effect_walk import raw_expression_mentions_parameter

_NON_CARRYING_BINARY_OPS = {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}


class OpaqueBorrowEffectExpressionsMixin:
    def _raw_expression_carries_parameter(self, expression, name) -> bool:
        if expression is None:
            return False
        if isinstance(expression, Identifier):
            return expression.name == name
        if isinstance(expression, CastExpr):
            return self._raw_expression_carries_parameter(expression.expr, name)
        if isinstance(expression, UnaryExpr):
            if expression.op == "&":
                return raw_expression_mentions_parameter(expression.operand, name)
            if expression.op == "!":
                return False
            if expression.op == "*":
                return bool(
                    self._opaque_projection_carrier_type(self._infer_type(expression))
                    and raw_expression_mentions_parameter(
                        expression.operand,
                        name,
                    )
                )
            return self._raw_expression_carries_parameter(expression.operand, name)
        if isinstance(expression, BinaryExpr):
            if expression.op in _NON_CARRYING_BINARY_OPS:
                return False
            return self._raw_expression_carries_parameter(
                expression.left,
                name,
            ) or self._raw_expression_carries_parameter(expression.right, name)
        if isinstance(expression, TernaryExpr):
            return self._raw_expression_carries_parameter(
                expression.true_expr,
                name,
            ) or self._raw_expression_carries_parameter(expression.false_expr, name)
        if isinstance(expression, (IndexExpr, FieldAccessExpr)):
            return bool(
                self._opaque_projection_carrier_type(self._infer_type(expression))
                and raw_expression_mentions_parameter(expression, name)
            )
        if isinstance(expression, CallExpr):
            return self._raw_hosted_alias_carries_parameter(expression, name)
        if isinstance(expression, NewExpr):
            return any(self._raw_expression_carries_parameter(argument, name) for argument in expression.args)
        if isinstance(expression, (BraceInitializer, ListLiteral, TupleLiteral)):
            return any(self._raw_expression_carries_parameter(element, name) for element in expression.elements)
        if isinstance(expression, MapLiteral):
            return any(
                self._raw_expression_carries_parameter(entry.key, name)
                or self._raw_expression_carries_parameter(entry.value, name)
                for entry in expression.entries
            )
        return False

    def _raw_hosted_alias_carries_parameter(self, expression, name) -> bool:
        callee = expression.callee
        if not isinstance(callee, Identifier):
            return False
        local_names = getattr(self, "_raw_borrow_proof_local_names", None)
        if not self._hosted_call_uses_owned_symbol(
            expression,
            local_names=local_names,
        ):
            return False
        parameter = hosted_return_alias_parameter(callee.name)
        return bool(
            parameter is not None
            and parameter < len(expression.args)
            and self._raw_expression_carries_parameter(
                expression.args[parameter],
                name,
            )
        )


__all__ = ["OpaqueBorrowEffectExpressionsMixin"]
