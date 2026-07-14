"""Ownership contracts for rebinding borrowed managed bindings."""

from ..ast_nodes import (
    CastExpr,
    CharLiteral,
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
            (NullLiteral, StringLiteral, CharLiteral),
        ):
            return False
        if isinstance(expression, Identifier):
            # Resolve the occurrence to its lexical symbol.  A borrowed
            # capture/parameter may safely be copied into another borrowed
            # proxy because neither slot claims ownership and both lifetimes
            # are bounded by the current call.  An owned local (or global)
            # remains unsafe even when it has the same spelling as a capture.
            symbol = self.scope.lookup(expression.name)
            return bool(
                symbol is None
                or symbol.owned_storage
                or symbol.kind
                not in {
                    "param",
                    "loop",
                    "parallel",
                    "catch",
                    "capture",
                    "lambda_param",
                }
            )
        if isinstance(expression, CastExpr):
            return self._managed_rebind_may_need_owner(expression.expr)
        if isinstance(expression, TernaryExpr):
            return self._managed_rebind_may_need_owner(expression.true_expr) or self._managed_rebind_may_need_owner(
                expression.false_expr
            )
        # Projections may die when their owning slot changes; calls, f-strings,
        # constructors, operators, and nested assignments may instead produce
        # an untracked +1. Neither lifetime fits a borrowed binding.
        return True


__all__ = ["ManagedRebindContractsMixin"]
