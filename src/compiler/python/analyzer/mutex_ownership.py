"""Ownership contracts for destructive Mutex operations."""

from ..ast_nodes import FieldAccessExpr, Identifier, IndexExpr


class MutexOwnershipContractsMixin:
    def _validate_mutex_destroy_receiver(self, expression) -> None:
        """Require one physical owned slot whose reference can be released."""
        receiver = expression.callee.obj
        if expression is not self._standalone_expression_root:
            self.context.error(
                "Mutex.destroy() must be a standalone expression statement",
                expression.line,
                expression.col,
            )
            return
        if expression.callee.optional:
            self.context.error(
                "Mutex.destroy() cannot use optional chaining; release a physical owned slot",
                expression.line,
                expression.col,
            )
            return
        indirect = (isinstance(receiver, FieldAccessExpr) and self._is_property_projection(receiver)) or (
            isinstance(receiver, IndexExpr) and self._is_protocol_index_projection(receiver)
        )
        if indirect or not self._is_lifetime_stable_storage(receiver):
            self.context.error(
                "Mutex.destroy() requires a physical owned slot; bind projections or temporaries to a local first",
                expression.line,
                expression.col,
            )
            return
        if not self._validate_mutable_target(receiver, expression.line, expression.col):
            return
        if not isinstance(receiver, Identifier):
            return
        symbol = self.scope.lookup(receiver.name)
        borrowed = {"param", "loop", "parallel", "catch", "capture", "lambda_param"}
        if symbol and symbol.kind in borrowed and not symbol.owned_storage:
            self.context.error(
                "Borrowed Mutex bindings cannot be destroyed; bind an owned local first",
                expression.line,
                expression.col,
            )


__all__ = ["MutexOwnershipContractsMixin"]
