"""Qualification-aware reference conversion contracts."""


class QualificationMixin:
    def _reference_shapes_compatible(self, target, source) -> bool:
        return bool(
            self._semantic_pointer_depth(target) == self._semantic_pointer_depth(source)
            and target.is_array == source.is_array
            and self._const_conversion_allowed(target, source)
            and self._generic_args_equal(target, source)
        )

    def _const_conversion_allowed(self, target, source) -> bool:
        """Whether an implicit conversion preserves pointee constness.

        ``is_const`` qualifies the base type, so it is an object qualifier for
        scalars and a pointee qualifier once one indirection is present. C's
        safe one-level qualification addition is allowed; removing const or
        changing a deeper pointee qualification requires an explicit cast.
        """
        target_depth = self._qualifier_indirection_depth(target)
        source_depth = self._qualifier_indirection_depth(source)
        if target_depth == 0 or source_depth == 0:
            return True
        if source.is_const and not target.is_const:
            return False
        if target_depth > 1 or source_depth > 1:
            return target.is_const == source.is_const
        return True

    def _qualifier_indirection_depth(self, type_expr) -> int:
        depth = self._semantic_pointer_depth(type_expr) + int(type_expr.is_array)
        if type_expr.base == "string" and depth == 0:
            return 1
        return depth


__all__ = ["QualificationMixin"]
