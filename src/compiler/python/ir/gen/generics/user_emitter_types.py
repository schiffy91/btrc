"""Type queries for monomorphized generic method emission."""

from __future__ import annotations


class _UserGenericTypeMixin:
    def _typedefs(self):
        return self._gen.analyzed.typedef_table if self._gen else None

    def _resolve_expr_type(self, expression):
        """Resolve an expression type through this specialization's type map."""
        from ....ast_nodes import FieldAccessExpr, Identifier, IndexExpr, SelfExpr

        override = self._arc_type_overrides.get(id(expression))
        if override is not None:
            return override
        if self._gen:
            analyzed_type = self._gen.analyzed.node_types.get(id(expression))
            if analyzed_type:
                return self._resolve(analyzed_type)
        if isinstance(expression, Identifier):
            lexical_type = self._var_types.get(expression.name)
            if lexical_type is not None:
                return lexical_type
            if self._gen:
                global_type = self._gen.analyzed.global_var_types.get(
                    expression.name,
                )
                if global_type is not None:
                    return self._resolve(global_type)
            return None
        if isinstance(expression, SelfExpr):
            return self._self_type()
        if isinstance(expression, FieldAccessExpr):
            receiver_type = (
                self._self_type() if isinstance(expression.obj, SelfExpr) else self._resolve_expr_type(expression.obj)
            )
            return self._member_type(receiver_type, expression.field)
        if isinstance(expression, IndexExpr):
            return self._indexed_type(self._resolve_expr_type(expression.obj))
        return None

    def _self_type(self):
        from ....ast_nodes import TypeExpr

        class_info = getattr(self, "_cls_info", None)
        if not class_info:
            return None
        return TypeExpr(
            base=class_info.name,
            generic_args=[self.type_map[name] for name in class_info.generic_params],
        )

    def _member_type(self, receiver_type, field_name: str):
        if not self._gen or not receiver_type:
            return None
        class_info = self._gen.analyzed.class_table.get(receiver_type.base)
        if not class_info:
            return None
        fields = getattr(class_info, "fields", {})
        properties = getattr(class_info, "properties", {})
        member = fields.get(field_name) or properties.get(field_name)
        if not member or not member.type:
            return None
        from .core import _resolve_type

        substitutions = dict(zip(class_info.generic_params, receiver_type.generic_args))
        return self._resolve(
            _resolve_type(
                member.type,
                substitutions,
                self._typedefs(),
                self.type_identity,
            )
        )

    def _indexed_type(self, container_type):
        if not container_type:
            return None
        if container_type.base in ("Vector", "List", "Array", "Set"):
            if len(container_type.generic_args) == 1:
                return container_type.generic_args[0]
        if container_type.base == "Map" and len(container_type.generic_args) == 2:
            return container_type.generic_args[1]
        if container_type.base == "string":
            from ....ast_nodes import TypeExpr

            return TypeExpr(base="char")
        if container_type.is_array:
            from ....type_composition import strip_outer_storage

            return strip_outer_storage(container_type, array=True)
        if container_type.pointer_depth > 0:
            from ....type_composition import strip_outer_storage

            return strip_outer_storage(container_type)
        return None

    def _mangle_type(self, type_expr):
        """Return a concrete class/collection C prefix, when available."""
        if not type_expr:
            return None
        if getattr(type_expr, "generic_args", None):
            return self.type_identity.specialization_symbol(
                type_expr.base,
                type_expr.generic_args,
            )
        if self._gen and type_expr.base in self._gen.analyzed.class_table:
            class_info = self._gen.analyzed.class_table[type_expr.base]
            if not class_info.generic_params:
                return type_expr.base
        return None

    def _class_destroy_fn(self, resolved):
        if not self._gen or not resolved:
            return None

        if not self._gen.managed_values.is_class(resolved):
            return None
        class_info = self._gen.analyzed.class_table.get(resolved.base)
        if not class_info:
            return None
        if getattr(resolved, "generic_args", None):
            target = self.type_identity.specialization_symbol(
                resolved.base,
                resolved.generic_args,
            )
            return f"{target}_destroy"
        if class_info.generic_params:
            return None
        return f"{resolved.base}_destroy"


__all__ = ["_UserGenericTypeMixin"]
