"""Semantic classification of managed source value types."""

from ...type_composition import nullable_collapses_reference_layer
from ...type_identity import TypeIdentity


class ManagedTypeClassifier:
    """Classify managed domains from analyzed type data only."""

    def __init__(self, analyzed, type_identity: TypeIdentity) -> None:
        self.analyzed = analyzed
        self.type_identity = type_identity

    def canonical(self, type_expr):
        if type_expr is None:
            return None
        from .type_resolution import canonical_type

        return canonical_type(type_expr, self.analyzed.typedef_table)

    def is_string(self, type_expr) -> bool:
        return self.type_identity.is_scalar_string(self.canonical(type_expr))

    def is_class(self, type_expr) -> bool:
        canonical = self.canonical(type_expr)
        depth = canonical.pointer_depth - int(nullable_collapses_reference_layer(canonical)) if canonical else 0
        return bool(
            canonical is not None
            and not canonical.is_array
            and depth <= 1
            and canonical.base in self.analyzed.class_table
        )

    def is_mutex(self, type_expr) -> bool:
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

    def is_arc(self, type_expr) -> bool:
        return self.is_class(type_expr) or self.is_mutex(type_expr)

    def is_managed(self, type_expr) -> bool:
        return self.is_string(type_expr) or self.is_arc(type_expr)


__all__ = ["ManagedTypeClassifier"]
