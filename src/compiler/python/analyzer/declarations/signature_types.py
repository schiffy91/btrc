"""Type relations required by declaration-signature validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...type_composition import nullable_collapses_reference_layer
from ...type_identity import TypeShapeError, substitute_type_expr
from .type_resolution import canonical_declaration_type

if TYPE_CHECKING:
    from ...ast_nodes import TypeExpr
    from ..analysis_context import AnalysisContext
    from .registry import DeclarationRegistry


class SignatureTypePolicy:
    """Own canonical equality and substitution for callable signatures."""

    def __init__(
        self,
        context: AnalysisContext,
        registry: DeclarationRegistry,
    ) -> None:
        self.context = context
        self.registry = registry
        self._reported_shape_errors: set[tuple[str, int, int]] = set()

    def equal(self, left: TypeExpr | None, right: TypeExpr | None) -> bool:
        """Compare signature types after typedef and reference normalization."""
        if left is None or right is None:
            return left is right
        left = self.canonical(left)
        right = self.canonical(right)
        if (
            left.base != right.base
            or self._semantic_pointer_depth(left) != self._semantic_pointer_depth(right)
            or left.is_array != right.is_array
            or left.is_nullable != right.is_nullable
            or left.is_const != right.is_const
            or left.is_volatile != right.is_volatile
        ):
            return False
        left_args = left.generic_args or []
        right_args = right.generic_args or []
        return len(left_args) == len(right_args) and all(
            self.equal(first, second) for first, second in zip(left_args, right_args)
        )

    def substitute(
        self,
        type_expr: TypeExpr | None,
        substitutions: dict[str, TypeExpr],
    ) -> TypeExpr | None:
        """Substitute signature parameters and report unrepresentable shapes."""
        try:
            return substitute_type_expr(
                type_expr,
                substitutions,
                reference_resolver=self.canonical,
            )
        except TypeShapeError as error:
            bad_type = error.type_expr or type_expr
            line = getattr(bad_type, "line", 0) or getattr(type_expr, "line", 0)
            col = getattr(bad_type, "col", 0) or getattr(type_expr, "col", 0)
            marker = (str(error), line, col)
            if marker not in self._reported_shape_errors:
                self._reported_shape_errors.add(marker)
                self.context.error(str(error), line, col)
            return type_expr

    def canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return canonical_declaration_type(
            type_expr,
            self.registry.typedef_table,
        )

    @staticmethod
    def _semantic_pointer_depth(type_expr: TypeExpr) -> int:
        depth = type_expr.pointer_depth
        intrinsic_base = type_expr.base in {"string", "Thread", "Mutex", "__fn_ptr"}
        if nullable_collapses_reference_layer(
            type_expr,
            base_is_reference=intrinsic_base,
        ):
            depth -= 1
        if intrinsic_base:
            depth += 1
        elif type_expr.base in {"Vector", "List", "Map", "Set", "Array"} and type_expr.generic_args and depth == 0:
            depth = 1
        return depth


__all__ = ["SignatureTypePolicy"]
