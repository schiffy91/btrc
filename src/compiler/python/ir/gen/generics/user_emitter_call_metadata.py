"""Resolve declarations and receivers for generic-method calls."""


class _UserGenericCallMetadataMixin:
    def _callable_for_call(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        if not self._gen:
            return None
        callee = expression.callee
        if isinstance(callee, Identifier):
            class_info = self._gen.analyzed.class_table.get(callee.name)
            if class_info is not None:
                return class_info.constructor
            return self._gen.analyzed.function_table.get(callee.name)
        if not isinstance(callee, FieldAccessExpr):
            return None
        if isinstance(callee.obj, SelfExpr):
            return self._cls_info.methods.get(callee.field) if self._cls_info else None
        if isinstance(callee.obj, Identifier):
            class_info = self._gen.analyzed.class_table.get(callee.obj.name)
            if class_info is not None:
                method = class_info.methods.get(callee.field)
                if method is not None:
                    return method
        receiver_type = self._resolve_expr_type(callee.obj)
        class_info = self._gen.analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
        return class_info.methods.get(callee.field) if class_info else None

    def _params_for_call(self, expression):
        declaration = self._callable_for_call(expression)
        return declaration.params if declaration is not None else []

    def _instance_receiver(self, expression):
        from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

        callee = expression.callee
        if not isinstance(callee, FieldAccessExpr):
            return None
        if isinstance(callee.obj, SelfExpr):
            return None
        if isinstance(callee.obj, Identifier) and self._gen:
            if callee.obj.name in self._gen.analyzed.class_table:
                return None
        return callee.obj


__all__ = ["_UserGenericCallMetadataMixin"]
