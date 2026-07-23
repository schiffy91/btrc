"""F-string lowering for monomorphized generic method bodies."""


class _UserGenericFStringMixin:
    def _fstring(self, node):
        from ..fstrings import lower_typed_fstring

        return lower_typed_fstring(
            self._gen,
            node,
            ownership=self._boundary_ownership,
            lower_value=self._expr,
            type_of=self._resolve_expr_type,
            owns=self._owns_expr,
            render_type=self.iter_value_c,
            activate_cleanup=self._activate_cleanup_registration,
        )


__all__ = ["_UserGenericFStringMixin"]
