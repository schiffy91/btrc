"""Semantic ownership for host-side GPU dispatch contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from ..ast_nodes import AssignExpr, CallExpr, Identifier, TypeExpr
from ..type_composition import strip_outer_storage
from ..type_identity import TypeIdentity
from .core_models import Scope

if TYPE_CHECKING:
    from .analysis_context import AnalysisContext
    from .declarations.registry import DeclarationRegistry


GPU_ARRAY_RESULT_CONTEXT_DIAGNOSTIC = (
    "Array-returning @gpu call is only valid as an array declaration initializer or direct array assignment statement"
)


class GpuDispatchValidator:
    """Own host storage and materialization rules for GPU dispatches."""

    def __init__(
        self,
        context: AnalysisContext,
        declarations: DeclarationRegistry,
        *,
        canonical_type: Callable[[TypeExpr | None], TypeExpr | None],
        analyze_expression: Callable[[object], None],
        type_identity: TypeIdentity,
    ) -> None:
        self._context = context
        self._declarations = declarations
        self._canonical_type = canonical_type
        self._analyze_expression = analyze_expression
        self._type_identity = type_identity
        self._array_result_boundary: object | None = None

    def is_array_result(self, expression: object, scope: Scope) -> bool:
        """Whether ``expression`` invokes an array-returning GPU kernel."""
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return False
        name = expression.callee.name
        symbol = scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        function = self._declarations.function_table.get(name)
        return bool(function and function.is_gpu and function.return_type.is_array)

    def is_output_assignment(self, expression: object, scope: Scope) -> bool:
        """Whether an assignment materializes a GPU result into host storage."""
        return bool(
            isinstance(expression, AssignExpr)
            and expression.op == "="
            and self.is_array_result(expression.value, scope)
        )

    def validate_result_context(self, expression: object, scope: Scope) -> None:
        """Reject an output dispatch unless this exact call owns the boundary."""
        if self.is_array_result(expression, scope) and expression is not self._array_result_boundary:
            self._context.error(
                GPU_ARRAY_RESULT_CONTEXT_DIAGNOSTIC,
                getattr(expression, "line", 0),
                getattr(expression, "col", 0),
            )

    def analyze_array_initializer(
        self,
        expression: object,
        declared_type: TypeExpr | None,
        scope: Scope,
    ) -> None:
        """Analyze a declaration initializer with permission for its root call."""
        declared = self._canonical_type(declared_type)
        array_storage = declared_type is None or bool(declared and declared.is_array)
        boundary = expression if array_storage and self.is_array_result(expression, scope) else None
        self._analyze_result_boundary(expression, boundary)

    def analyze_result_statement(self, expression: object, scope: Scope) -> None:
        """Analyze an expression statement, permitting only a direct output RHS."""
        boundary = expression.value if self.is_output_assignment(expression, scope) else None
        self._analyze_result_boundary(expression, boundary)

    def input_has_compatible_storage(self, expected: TypeExpr, actual: TypeExpr) -> bool:
        """Whether an input buffer has the exact unqualified GPU ABI shape."""
        canonical = self._canonical_type(actual)
        element = self._buffer_element_type(actual)
        return bool(
            canonical is not None
            and element is not None
            and not canonical.is_volatile
            and not element.is_volatile
            and self._buffer_elements_exact(expected, actual)
        )

    def output_element_compatible(self, target: TypeExpr, source: TypeExpr) -> bool:
        """Whether a writable host target exactly matches a GPU result element."""
        canonical = self._canonical_type(target)
        element = self._buffer_element_type(target)
        return bool(
            canonical is not None
            and element is not None
            and not canonical.is_const
            and not canonical.is_volatile
            and not element.is_const
            and not element.is_volatile
            and self._buffer_elements_exact(target, source)
        )

    def _analyze_result_boundary(self, expression: object, boundary: object | None) -> None:
        previous = self._array_result_boundary
        self._array_result_boundary = boundary
        try:
            self._analyze_expression(expression)
        finally:
            self._array_result_boundary = previous

    def _buffer_element_type(self, type_expr: TypeExpr) -> TypeExpr | None:
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return None
        if canonical.base in {"Array", "Vector"} and len(canonical.generic_args) == 1:
            element = self._canonical_type(canonical.generic_args[0])
        elif canonical.is_array:
            element = self._canonical_type(strip_outer_storage(canonical, array=True))
        else:
            return None
        if element is None:
            return None
        return replace(element, is_static=False, is_extern=False)

    def _buffer_elements_exact(self, expected: TypeExpr, actual: TypeExpr) -> bool:
        expected_element = self._buffer_element_type(expected)
        actual_element = self._buffer_element_type(actual)
        return bool(
            expected_element is not None
            and actual_element is not None
            and self._type_identity.shape_key(expected_element) == self._type_identity.shape_key(actual_element)
        )


__all__ = ["GpuDispatchValidator"]
