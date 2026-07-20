"""Resolve declarations and receivers for generic-method calls."""


class _UserGenericCallMetadataMixin:
    def _resolved_generic_constructor(self, expression, class_info):
        """Return the concrete constructor symbol and parameter contract."""
        instance_type = self._resolve_expr_type(expression)
        complete_instance = bool(
            instance_type is not None
            and instance_type.base == class_info.name
            and len(instance_type.generic_args) == len(class_info.generic_params)
        )
        if not complete_instance and self._cls_info is class_info:
            instance_type = self._self_type()
            complete_instance = instance_type is not None
        if not complete_instance:
            from ..errors import CodegenError

            raise CodegenError(f"Cannot resolve generic constructor instance '{class_info.name}'")

        from ..types import mangle_generic_type
        from .user_call_arguments import resolved_generic_parameters

        substitutions = dict(zip(class_info.generic_params, instance_type.generic_args))
        params = resolved_generic_parameters(
            self,
            class_info.constructor.params if class_info.constructor else [],
            substitutions,
        )
        return (
            mangle_generic_type(instance_type.base, instance_type.generic_args),
            params,
        )

    def _callable_field(self, expression):
        from ....ast_nodes import FieldAccessExpr

        if not isinstance(expression.callee, FieldAccessExpr):
            return False
        from ..type_resolution import function_pointer_signature

        return (
            function_pointer_signature(
                self._resolve_expr_type(expression.callee),
                self._typedefs(),
            )
            is not None
        )

    def _callable_for_call(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        if not self._gen:
            return None
        callee = expression.callee
        if isinstance(callee, Identifier):
            if callee.name in self._var_types:
                return None
            if id(expression) in self._gen.analyzed.hosted_call_ids:
                return None
            class_info = self._gen.analyzed.class_table.get(callee.name)
            if class_info is not None:
                return class_info.constructor
            return self._gen.analyzed.function_table.get(callee.name)
        if not isinstance(callee, FieldAccessExpr):
            return None
        from ..rich_enum_calls import rich_enum_variant_target

        variant = rich_enum_variant_target(
            self._gen,
            expression,
            identifier_is_local=lambda name: name in self._var_types,
        )
        if variant is not None:
            return variant[1]
        if isinstance(callee.obj, SelfExpr):
            return self._cls_info.methods.get(callee.field) if self._cls_info else None
        if isinstance(callee.obj, Identifier) and callee.obj.name not in self._var_types:
            class_info = self._gen.analyzed.class_table.get(callee.obj.name)
            if class_info is not None:
                method = class_info.methods.get(callee.field)
                if method is not None:
                    return method
        receiver_type = self._resolve_expr_type(callee.obj)
        class_info = self._gen.analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
        return class_info.methods.get(callee.field) if class_info else None

    def _params_for_call(self, expression):
        if not self._gen:
            return []
        from ..call_contracts import resolved_params_for_call

        params = resolved_params_for_call(
            self._gen,
            expression,
            type_of=self._resolve_expr_type,
            resolve_type=self._resolve,
            identifier_is_local=lambda name: name in self._var_types,
        )
        from .user_call_arguments import (
            call_target_substitutions,
            resolved_generic_parameters,
        )

        return resolved_generic_parameters(
            self,
            params,
            call_target_substitutions(self, expression),
        )

    def _instance_receiver(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        callee = expression.callee
        if not isinstance(callee, FieldAccessExpr):
            return None
        if isinstance(callee.obj, SelfExpr):
            return None
        if isinstance(callee.obj, Identifier) and self._gen:
            if callee.obj.name not in self._var_types and (
                callee.obj.name in self._gen.analyzed.class_table
                or callee.obj.name in self._gen.analyzed.rich_enum_table
            ):
                return None
        return callee.obj


__all__ = ["_UserGenericCallMetadataMixin"]
