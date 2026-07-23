"""Semantic identity and runtime naming for managed source values."""

from __future__ import annotations

from ...analyzer.core import AnalyzedProgram
from ...ast_nodes import TypeExpr
from ...type_composition import nullable_collapses_reference_layer
from ...type_identity import TypeIdentity
from .type_resolution import canonical_type

STRING_RUNTIME_NAME = "__btrc_managed_string"
MUTEX_RUNTIME_NAME = "__btrc_managed_mutex"


class ManagedValueSemantics:
    """Own managed-domain classification and concrete runtime names."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        type_identity: TypeIdentity,
    ) -> None:
        self.analyzed = analyzed
        self.type_identity = type_identity

    def canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return canonical_type(type_expr, self.analyzed.typedef_table)

    def is_string(self, type_expr: TypeExpr | None) -> bool:
        return self.type_identity.is_scalar_string(self.canonical(type_expr))

    def is_class(self, type_expr: TypeExpr | None) -> bool:
        canonical = self.canonical(type_expr)
        depth = canonical.pointer_depth - int(nullable_collapses_reference_layer(canonical)) if canonical else 0
        return bool(
            canonical is not None
            and not canonical.is_array
            and depth <= 1
            and canonical.base in self.analyzed.class_table
        )

    def is_mutex(self, type_expr: TypeExpr | None) -> bool:
        canonical = self.canonical(type_expr)
        depth = (
            canonical.pointer_depth
            - int(
                nullable_collapses_reference_layer(
                    canonical,
                    base_is_reference=True,
                )
            )
            if canonical
            else 0
        )
        return bool(
            canonical is not None
            and not canonical.is_array
            and depth == 0
            and canonical.base == "Mutex"
            and len(canonical.generic_args or ()) == 1
        )

    def is_arc(self, type_expr: TypeExpr | None) -> bool:
        return self.is_class(type_expr) or self.is_mutex(type_expr)

    def is_managed(self, type_expr: TypeExpr | None) -> bool:
        return self.is_string(type_expr) or self.is_arc(type_expr)

    def runtime_name(self, type_expr: TypeExpr) -> str:
        """Return the concrete ownership-bookkeeping name for a value."""
        if self.is_string(type_expr):
            return STRING_RUNTIME_NAME
        if self.is_mutex(type_expr):
            return MUTEX_RUNTIME_NAME
        canonical = self.canonical(type_expr)
        if canonical is None:
            raise ValueError("managed runtime names require a concrete type")
        info = self.analyzed.class_table.get(canonical.base)
        if canonical.generic_args and info is not None and info.generic_params:
            return self.type_identity.specialization_symbol(
                canonical.base,
                canonical.generic_args,
            )
        return canonical.base

    def local_value_type(
        self,
        type_expr: TypeExpr | None,
        emitted_name: str | None,
    ) -> TypeExpr | None:
        """Recover the source value retained by an ownership-provenance slot."""
        if emitted_name == STRING_RUNTIME_NAME:
            return TypeExpr(base="string")
        return type_expr

    def cleanup_destroy_symbol(self, emitted_name: str) -> str:
        if emitted_name == STRING_RUNTIME_NAME:
            return "__btrc_string_release_cleanup"
        if emitted_name == MUTEX_RUNTIME_NAME:
            return "__btrc_mutex_arc_destroy"
        return f"{emitted_name}_destroy"

    def destroy_symbol(self, type_expr: TypeExpr) -> str:
        """Return the terminal destroy callback for one managed value type."""
        if self.is_string(type_expr):
            return "__btrc_string_release_cleanup"
        if self.is_mutex(type_expr):
            return "__btrc_mutex_arc_destroy"
        return f"{self.runtime_name(type_expr)}_destroy"

    def emitted_value_c_type(self, emitted_name: str) -> str:
        """Return the exact C value type stored by lexical ownership state."""
        if emitted_name == STRING_RUNTIME_NAME:
            return "const char*"
        if emitted_name == MUTEX_RUNTIME_NAME:
            return "__btrc_mutex_val_t*"
        return f"struct {emitted_name}*"


__all__ = [
    "MUTEX_RUNTIME_NAME",
    "STRING_RUNTIME_NAME",
    "ManagedValueSemantics",
]
