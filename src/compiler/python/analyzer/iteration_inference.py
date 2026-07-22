"""Element-type inference for structural iteration protocols."""

from __future__ import annotations

from ..ast_nodes import TypeExpr
from ..type_composition import strip_outer_storage


class _IterationInferenceMixin:
    def _get_element_type(self, iter_type, line, col):
        """Get the element type for for-in iteration."""
        if iter_type is None:
            return None
        if iter_type.base == "string" or (iter_type.base == "char" and iter_type.pointer_depth >= 1):
            return TypeExpr(base="char")
        if iter_type.is_array:
            return strip_outer_storage(iter_type, array=True)
        if iter_type.base in {"Array", "List", "Set", "Vector"} and len(iter_type.generic_args) == 1:
            return iter_type.generic_args[0]
        if iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            return iter_type.generic_args[0]
        # Any class that implements iterGet participates in the iterable
        # protocol; generic arguments only affect its resolved return type.
        if iter_type.base in self.declarations.class_table:
            cls = self.declarations.class_table[iter_type.base]
            if "iterGet" in cls.methods:
                result = cls.methods["iterGet"].return_type
                if cls.generic_params and iter_type.generic_args:
                    substitutions = dict(zip(cls.generic_params, iter_type.generic_args))
                    return self._substitute_type(result, substitutions)
                return result
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None
        if iter_type.base in ("int", "float", "double", "bool"):
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None
        return None

    def _get_iter_value_type(self, iter_type, line, col):
        """Resolve the second binding type for key/value iteration."""
        if iter_type is None:
            return None
        if iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            return iter_type.generic_args[1]
        cls = self.declarations.class_table.get(iter_type.base)
        method = cls.methods.get("iterValueAt") if cls else None
        if method is None:
            self._error(
                f"Type '{iter_type.base}' does not support key/value iteration",
                line,
                col,
            )
            return None
        result = method.return_type
        if cls.generic_params and iter_type.generic_args:
            substitutions = dict(zip(cls.generic_params, iter_type.generic_args))
            result = self._substitute_type(result, substitutions)
        return result


__all__ = ["_IterationInferenceMixin"]
