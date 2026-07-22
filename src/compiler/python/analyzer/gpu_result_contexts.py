"""Materialization boundaries for array-returning GPU calls."""

from ..ast_nodes import AssignExpr

GPU_ARRAY_RESULT_CONTEXT_DIAGNOSTIC = (
    "Array-returning @gpu call is only valid as an array declaration initializer or direct array assignment statement"
)


class GpuResultContextContractsMixin:
    def _validate_gpu_array_result_context(self, expression) -> None:
        """Reject an output dispatch unless this exact call owns the boundary."""
        if self._is_gpu_array_initializer(expression) and expression is not self._gpu_array_result_boundary:
            self._error(
                GPU_ARRAY_RESULT_CONTEXT_DIAGNOSTIC,
                expression.line,
                expression.col,
            )

    def _analyze_gpu_array_initializer(self, expression, declared_type) -> None:
        """Analyze a declaration initializer with permission for its root call."""
        declared = self._canonical_type(declared_type)
        array_storage = declared_type is None or bool(declared and declared.is_array)
        boundary = expression if array_storage and self._is_gpu_array_initializer(expression) else None
        self._analyze_gpu_result_boundary(expression, boundary)

    def _analyze_gpu_result_statement(self, expression) -> None:
        """Analyze an expression statement, permitting only a direct output RHS."""
        boundary = None
        if isinstance(expression, AssignExpr) and expression.op == "=" and self._is_gpu_output_assignment(expression):
            boundary = expression.value
        self._analyze_gpu_result_boundary(expression, boundary)

    def _analyze_gpu_result_boundary(self, expression, boundary) -> None:
        previous = self._gpu_array_result_boundary
        self._gpu_array_result_boundary = boundary
        try:
            self._analyze_expr(expression)
        finally:
            self._gpu_array_result_boundary = previous


__all__ = ["GpuResultContextContractsMixin"]
