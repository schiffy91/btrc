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
            or (target_type.base not in {"string", "Mutex"} and target_type.base not in self.declarations.class_table)
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
        borrowed_self_projection = self._is_borrowed_self_projection(
            expression.value,
            expression.target.name,
        )
        needs_owner = expression.op != "=" or (
            not borrowed_self_projection
            and self._managed_rebind_may_need_owner(
                expression.value,
                target_type,
            )
        )
        if not needs_owner:
            return False
        self.context.error(
            "Borrowed managed bindings cannot be rebound; declare an owned "
            "local before assigning or applying a compound update",
            expression.line,
            expression.col,
        )
        return True

    def _managed_rebind_may_need_owner(self, expression, target_type=None) -> bool:
        if self._requires_string_conversion(
            target_type,
            self._infer_type(expression),
        ):
            return True
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
            return self._managed_rebind_may_need_owner(
                expression.expr,
                target_type,
            )
        if isinstance(expression, TernaryExpr):
            return self._managed_rebind_may_need_owner(
                expression.true_expr,
                target_type,
            ) or self._managed_rebind_may_need_owner(
                expression.false_expr,
                target_type,
            )
        # Projections may die when their owning slot changes; calls, f-strings,
        # constructors, operators, and nested assignments may instead produce
        # an untracked +1. Neither lifetime fits a borrowed binding.
        return True

    def _is_borrowed_self_projection(self, expression, target_name: str) -> bool:
        """Whether a physical projection remains rooted in the caller's owner."""
        if isinstance(expression, CastExpr):
            return self._is_borrowed_self_projection(expression.expr, target_name)
        if not isinstance(expression, FieldAccessExpr):
            return False

        from ..class_storage import custom_property_getter

        receiver_type = self._canonical_type(self._infer_type(expression.obj))
        if custom_property_getter(
            self.declarations.class_table,
            receiver_type,
            expression.field,
        ):
            return False

        root = expression.obj
        while isinstance(root, CastExpr):
            root = root.expr
        if isinstance(root, Identifier):
            return root.name == target_name
        return self._is_borrowed_self_projection(root, target_name)


__all__ = ["ManagedRebindContractsMixin"]
