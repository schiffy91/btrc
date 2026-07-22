"""Result-type inference for indexed expressions."""

from ..ast_nodes import TypeExpr
from ..index_protocol import indexed_protocol
from ..qualifier_provenance import strip_outer_storage_through_typedef
from ..reference_semantics import is_scalar_string_type
from ..type_composition import strip_outer_storage


class _IndexTypeInferenceMixin:
    def _infer_index_type(self, expression):
        object_type = self._infer_type(expression.obj)
        canonical = self._canonical_type(object_type)
        if canonical and canonical.base in {"Vector", "List", "Array", "Set"} and len(canonical.generic_args) == 1:
            return canonical.generic_args[0]
        if canonical and canonical.base == "Map" and len(canonical.generic_args) == 2:
            return canonical.generic_args[1]
        if is_scalar_string_type(canonical):
            return TypeExpr(base="char", is_const=canonical.is_const)
        if (
            canonical
            and (canonical.is_array or canonical.pointer_depth > 0)
            and (
                canonical.is_array
                or canonical.base in self._active_storage_type_parameters()
                or canonical.base not in self.class_table
                or canonical.pointer_depth > 1
            )
        ):
            preserved = strip_outer_storage_through_typedef(
                object_type,
                self.typedef_table,
            )
            if preserved is not None:
                return preserved
            return strip_outer_storage(canonical, array=canonical.is_array)

        protocol = indexed_protocol(
            canonical,
            self.class_table,
            active_type_params=self._active_storage_type_parameters(),
        )
        if protocol is None:
            return None
        getter = protocol.getter
        setter = protocol.setter
        value_type = getter.return_type if getter is not None else None
        if value_type is None and setter is not None:
            value_type = setter.params[1].type
        if value_type is not None and canonical.generic_args:
            value_type = self._substitute_type(
                value_type,
                protocol.substitutions(canonical),
            )
        return value_type


__all__ = ["_IndexTypeInferenceMixin"]
