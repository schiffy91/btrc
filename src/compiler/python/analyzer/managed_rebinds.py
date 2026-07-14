"""Ownership contracts for rebinding borrowed managed bindings."""

from ..ast_nodes import (
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    Identifier,
    NullLiteral,
    StringLiteral,
    TernaryExpr,
)


class ManagedRebindContractsMixin:
    def _reject_borrowed_managed_rebind(
        self,
        expression,
        target_type,
    ) -> bool:
        if (
            not isinstance(expression.target, Identifier)
            or target_type is None
            or (target_type.base != "string" and target_type.base not in self.class_table)
        ):
            return False
        symbol = self.scope.lookup(expression.target.name)
        if (
            symbol is None
            or symbol.kind
            not in {
                "param",
                "loop",
                "parallel",
                "catch",
                "capture",
                "lambda_param",
            }
            or symbol.owned_storage
        ):
            return False
        needs_owner = expression.op != "=" or self._managed_rebind_may_need_owner(expression.value)
        if not needs_owner:
            return False
        self._error(
            "Borrowed managed bindings cannot be rebound; declare an owned "
            "local before assigning or applying a compound update",
            expression.line,
            expression.col,
        )
        return True

    def _managed_rebind_may_need_owner(self, expression) -> bool:
        if isinstance(
            expression,
            (NullLiteral, StringLiteral, CharLiteral, Identifier),
        ):
            return False
        if isinstance(expression, CastExpr):
            return self._managed_rebind_may_need_owner(expression.expr)
        if isinstance(expression, FieldAccessExpr):
            return self._argument_produces_owned_result(expression)
        if isinstance(expression, TernaryExpr):
            return self._managed_rebind_may_need_owner(expression.true_expr) or self._managed_rebind_may_need_owner(
                expression.false_expr
            )
        # Calls, protocol getters, f-strings, concatenation, constructors,
        # overloaded operators, and nested assignments may all produce +1.
        return True


__all__ = ["ManagedRebindContractsMixin"]
