"""Strict-C contracts for fixed-size array objects."""

from ..ast_nodes import BraceInitializer, CallExpr, Identifier, IntLiteral, ListLiteral


class ArrayContractsMixin:
    def _validate_fixed_array_initializer(
        self,
        expected,
        initializer,
        subject,
        line,
        col,
    ) -> None:
        """Reject initializer lists that exceed a statically known bound."""
        if expected is None or not expected.is_array:
            return
        bound = expected.array_size
        if not isinstance(bound, IntLiteral):
            return
        if not isinstance(initializer, (BraceInitializer, ListLiteral)):
            return
        count = len(initializer.elements)
        if count > bound.value:
            self._error(
                f"{subject} has {count} elements but fixed array bound is {bound.value}",
                line,
                col,
            )

    def _validate_fixed_array_assignment(self, target, expression) -> bool:
        """Reject assignment to an array object; C arrays are not assignable."""
        if target is None or not target.is_array or target.array_size is None:
            return False
        if self._is_gpu_output_assignment(expression):
            return False
        self._error(
            f"Fixed array '{self._format_type(target)}' is not assignable",
            expression.line,
            expression.col,
        )
        return True

    def _is_gpu_output_assignment(self, expression) -> bool:
        """Recognize the GPU dispatch lowering that writes into a host buffer."""
        if expression.op != "=" or not isinstance(expression.value, CallExpr):
            return False
        callee = expression.value.callee
        if not isinstance(callee, Identifier):
            return False
        declaration = self.function_table.get(callee.name)
        return bool(declaration and declaration.is_gpu and declaration.return_type and declaration.return_type.is_array)


__all__ = ["ArrayContractsMixin"]
