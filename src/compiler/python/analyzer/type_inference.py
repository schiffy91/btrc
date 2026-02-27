"""Type inference: _infer_type, _infer_lambda_return, _get_element_type."""

from ..ast_nodes import (
    AssignExpr, BinaryExpr, BoolLiteral, CallExpr, CastExpr,
    CharLiteral, FieldAccessExpr, FloatLiteral, Identifier,
    IndexExpr, IntLiteral, LambdaExpr, ListLiteral, MapLiteral,
    NewExpr, NullLiteral, ReturnStmt, SelfExpr, StringLiteral,
    TernaryExpr, TupleLiteral, TypeExpr, UnaryExpr,
    LambdaBlock,
)


class TypeInferenceMixin:

    def _infer_type(self, expr) -> TypeExpr | None:
        """Best-effort type inference. Returns None if unknown."""
        if isinstance(expr, IntLiteral):
            return TypeExpr(base="int")
        elif isinstance(expr, FloatLiteral):
            return TypeExpr(base="float")
        elif isinstance(expr, StringLiteral):
            return TypeExpr(base="string")
        elif isinstance(expr, CharLiteral):
            return TypeExpr(base="char")
        elif isinstance(expr, BoolLiteral):
            return TypeExpr(base="bool")
        elif isinstance(expr, NullLiteral):
            return TypeExpr(base="void", pointer_depth=1)
        elif isinstance(expr, Identifier):
            sym = self.scope.lookup(expr.name)
            if sym:
                return sym.type
            return None
        elif isinstance(expr, SelfExpr):
            if self.current_class:
                return TypeExpr(base=self.current_class.name, pointer_depth=1)
            return None
        elif isinstance(expr, FieldAccessExpr):
            return self._infer_field_access_type(expr)
        elif isinstance(expr, CallExpr):
            return self._infer_call_type(expr)
        elif isinstance(expr, NewExpr):
            return TypeExpr(base=expr.type.base, generic_args=expr.type.generic_args,
                            pointer_depth=1)
        elif isinstance(expr, IndexExpr):
            obj_type = self._infer_type(expr.obj)
            if obj_type and obj_type.base in ("List", "Array") and obj_type.generic_args:
                return obj_type.generic_args[0]
            if (obj_type and obj_type.base == "Map" and obj_type.generic_args
                    and len(obj_type.generic_args) == 2):
                return obj_type.generic_args[1]
            return None
        elif isinstance(expr, BinaryExpr):
            return self._infer_binary_type(expr)
        elif isinstance(expr, CastExpr):
            return expr.target_type
        elif isinstance(expr, UnaryExpr):
            return self._infer_type(expr.operand)
        elif isinstance(expr, TernaryExpr):
            return self._infer_type(expr.true_expr)
        elif isinstance(expr, AssignExpr):
            return self._infer_type(expr.target)
        elif isinstance(expr, LambdaExpr):
            if expr.return_type:
                ret = expr.return_type
            else:
                ret = self._infer_lambda_return(expr)
            param_types = [p.type for p in expr.params]
            return TypeExpr(base="__fn_ptr", generic_args=[ret] + param_types)
        elif isinstance(expr, TupleLiteral):
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            return TypeExpr(base="Tuple", generic_args=elem_types)
        elif isinstance(expr, ListLiteral):
            if expr.elements:
                elem_type = self._infer_type(expr.elements[0])
                if elem_type:
                    return TypeExpr(base="List", generic_args=[elem_type])
            return TypeExpr(base="List", generic_args=[TypeExpr(base="int")])
        elif isinstance(expr, MapLiteral):
            if expr.entries:
                key_type = self._infer_type(expr.entries[0].key)
                val_type = self._infer_type(expr.entries[0].value)
                if key_type and val_type:
                    return TypeExpr(base="Map", generic_args=[key_type, val_type])
            return TypeExpr(base="Map",
                            generic_args=[TypeExpr(base="string"), TypeExpr(base="int")])
        return None

    def _infer_field_access_type(self, expr):
        obj_type = self._infer_type(expr.obj)
        if obj_type and obj_type.base in self.rich_enum_table:
            if expr.field == "tag":
                return TypeExpr(base="int")
            return None
        if (isinstance(expr.obj, FieldAccessExpr)
                and isinstance(expr.obj.obj, FieldAccessExpr)):
            data_expr = expr.obj.obj
            if isinstance(data_expr.obj, (Identifier, FieldAccessExpr)):
                s_type = self._infer_type(data_expr.obj)
                if s_type and s_type.base in self.rich_enum_table:
                    enum_decl = self.rich_enum_table[s_type.base]
                    variant_name = expr.obj.field
                    for v in enum_decl.variants:
                        if v.name == variant_name:
                            for p in v.params:
                                if p.name == expr.field:
                                    return p.type
        if obj_type and obj_type.base in self.class_table:
            cls = self.class_table[obj_type.base]
            field_type = None
            if expr.field in cls.properties:
                field_type = cls.properties[expr.field].type
            elif expr.field in cls.fields:
                field_type = cls.fields[expr.field].type
            if field_type and cls.generic_params and obj_type.generic_args:
                subs = dict(zip(cls.generic_params, obj_type.generic_args))
                if field_type.base in subs:
                    return subs[field_type.base]
            return field_type
        return None

    def _infer_call_type(self, expr):
        if isinstance(expr.callee, Identifier):
            if expr.callee.name in self.class_table:
                return TypeExpr(base=expr.callee.name, pointer_depth=1)
            if expr.callee.name in self.function_table:
                return self.function_table[expr.callee.name].return_type
        if isinstance(expr.callee, FieldAccessExpr):
            obj_type = self._infer_type(expr.callee.obj)
            if (obj_type and obj_type.base in ("int", "float", "double", "long", "bool")
                    and obj_type.pointer_depth == 0):
                if expr.callee.field == "toString":
                    return TypeExpr(base="string")
            if obj_type and (obj_type.base == "string" or
                             (obj_type.base == "char" and obj_type.pointer_depth >= 1)):
                return self._string_method_return_type(expr.callee.field)
            if obj_type and obj_type.base == "Map" and len(obj_type.generic_args) == 2:
                return self._map_method_return_type(expr.callee.field, obj_type)
            if obj_type and obj_type.base == "List" and obj_type.generic_args:
                return self._list_method_return_type(expr.callee.field, obj_type)
            if obj_type and obj_type.base == "Set" and obj_type.generic_args:
                return self._set_method_return_type(expr.callee.field, obj_type)
            if obj_type and obj_type.base in self.class_table:
                cls = self.class_table[obj_type.base]
                if expr.callee.field in cls.methods:
                    ret = cls.methods[expr.callee.field].return_type
                    if cls.generic_params and obj_type.generic_args:
                        subs = dict(zip(cls.generic_params, obj_type.generic_args))
                        if ret and ret.base in subs:
                            return subs[ret.base]
                    return ret
            if (isinstance(expr.callee.obj, Identifier)
                    and expr.callee.obj.name in self.class_table):
                cls = self.class_table[expr.callee.obj.name]
                if expr.callee.field in cls.methods:
                    return cls.methods[expr.callee.field].return_type
        return None

    def _infer_binary_type(self, expr):
        left_type = self._infer_type(expr.left)
        right_type = self._infer_type(expr.right)
        if expr.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
            return TypeExpr(base="bool")
        if left_type and right_type:
            if left_type.base == "double" or right_type.base == "double":
                return TypeExpr(base="double")
            if left_type.base == "float" or right_type.base == "float":
                return TypeExpr(base="float")
            if left_type.base == "long" or right_type.base == "long":
                return TypeExpr(base="long")
            if left_type.base == "int" and right_type.base == "int":
                return TypeExpr(base="int")
        return left_type or right_type

    def _infer_lambda_return(self, expr) -> TypeExpr:
        """Infer the return type of a lambda from its body."""
        if isinstance(expr.body, LambdaBlock):
            for stmt in expr.body.body.statements:
                if isinstance(stmt, ReturnStmt) and stmt.value:
                    t = self._infer_type(stmt.value)
                    if t:
                        return t
        return TypeExpr(base="int")

    def _get_element_type(self, iter_type, line, col):
        """Get the element type for for-in iteration."""
        if iter_type is None:
            return None
        if iter_type.base in ("List", "Array", "Set") and iter_type.generic_args:
            return iter_type.generic_args[0]
        if (iter_type.base == "string"
                or (iter_type.base == "char" and iter_type.pointer_depth >= 1)):
            return TypeExpr(base="char")
        if iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            return None
        if iter_type.base in self.class_table:
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None
        if iter_type.base in ("int", "float", "double", "bool"):
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None
        return None
