"""Type inference: _infer_type, _infer_lambda_return, _get_element_type."""

from __future__ import annotations

from dataclasses import replace

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CallExpr,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    FStringLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SizeofExpr,
    SpawnExpr,
    StringLiteral,
    TernaryExpr,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
)
from ..numeric_literals import float_literal_type
from ..reference_semantics import is_scalar_string_type
from .c_call_types import (
    c_integer_identifier,
    c_opaque_value_identifier,
    c_predefined_identifier_type,
)
from .iteration_inference import _IterationInferenceMixin


class TypeInferenceMixin(_IterationInferenceMixin):
    def _infer_type(self, expr) -> TypeExpr | None:
        """Infer a type, memoizing results to avoid quadratic re-inference."""
        if expr is None:
            return None
        cached = self.node_types.get(id(expr))
        if cached is not None:
            return self._record_node_type(expr, cached)
        result = self._infer_type_uncached(expr)
        return self._record_node_type(expr, result)

    def _infer_type_uncached(self, expr) -> TypeExpr | None:
        if isinstance(expr, IntLiteral):
            return self._infer_integer_literal_type(expr.raw, expr.value)
        elif isinstance(expr, FloatLiteral):
            return TypeExpr(base=float_literal_type(expr.raw))
        elif isinstance(expr, StringLiteral):
            return TypeExpr(base="string")
        elif isinstance(expr, CharLiteral):
            return TypeExpr(base="char")
        elif isinstance(expr, BoolLiteral):
            return TypeExpr(base="bool")
        elif isinstance(expr, FStringLiteral):
            return TypeExpr(base="string")
        elif isinstance(expr, SizeofExpr):
            return TypeExpr(base="size_t")
        elif isinstance(expr, NullLiteral):
            return TypeExpr(base="void", pointer_depth=1, is_nullable=True)
        elif isinstance(expr, Identifier):
            if expr.name == "NULL":
                return TypeExpr(base="void", pointer_depth=1, is_nullable=True)
            sym = self.scope.lookup(expr.name)
            if sym:
                return sym.type
            function = self.function_table.get(expr.name)
            if function:
                return TypeExpr(
                    base="__fn_ptr",
                    generic_args=[function.return_type, *(param.type for param in function.params)],
                )
            owners = self._enum_member_owners.get(expr.name, set())
            if len(owners) == 1:
                owner = next(iter(owners))
                return TypeExpr(base=owner or "int")
            if expr.name in {"stdin", "stdout", "stderr"}:
                return TypeExpr(base="FILE", pointer_depth=1)
            if expr.name == "__func__":
                return TypeExpr(base="char", pointer_depth=1, is_const=True)
            predefined = c_predefined_identifier_type(expr.name)
            if predefined == "const char*":
                return TypeExpr(base="char", pointer_depth=1, is_const=True)
            if predefined is not None:
                return TypeExpr(base=predefined)
            if c_opaque_value_identifier(expr.name):
                return None
            if c_integer_identifier(expr.name):
                return TypeExpr(base="int")
            return None
        elif isinstance(expr, SelfExpr):
            if self.current_class:
                return self._current_self_type()
            return None
        elif isinstance(expr, FieldAccessExpr):
            return self._infer_field_access_type(expr)
        elif isinstance(expr, CallExpr):
            return self._infer_call_type(expr)
        elif isinstance(expr, NewExpr):
            if expr.type.base in ("Thread", "Mutex"):
                return replace(expr.type, pointer_depth=0)
            return TypeExpr(base=expr.type.base, generic_args=expr.type.generic_args, pointer_depth=1)
        elif isinstance(expr, IndexExpr):
            obj_type = self._infer_type(expr.obj)
            if obj_type and obj_type.base in ("Vector", "List", "Array", "Set") and len(obj_type.generic_args) == 1:
                # Generic with 1 arg (List, Array, Set): element = args[0]
                return obj_type.generic_args[0]
            if obj_type and obj_type.base == "Map" and len(obj_type.generic_args) == 2:
                return obj_type.generic_args[1]
            if is_scalar_string_type(obj_type):
                return TypeExpr(base="char", is_const=obj_type.is_const)
            if obj_type and obj_type.is_array:
                from ..type_composition import strip_outer_storage

                return strip_outer_storage(obj_type, array=True)
            if (
                obj_type
                and obj_type.pointer_depth > 0
                and (obj_type.base not in self.class_table or obj_type.pointer_depth > 1)
            ):
                from ..type_composition import strip_outer_storage

                return strip_outer_storage(obj_type)
            from ..index_protocol import indexed_protocol

            protocol = indexed_protocol(obj_type, self.class_table)
            if protocol is not None:
                getter = protocol.getter
                setter = protocol.setter
                value_type = None
                if getter is not None:
                    value_type = getter.return_type
                elif setter is not None:
                    value_type = setter.params[1].type
                if value_type is not None and obj_type.generic_args:
                    substitutions = protocol.substitutions(obj_type)
                    value_type = self._substitute_type(value_type, substitutions)
                if value_type is not None:
                    return value_type
            return None
        elif isinstance(expr, BinaryExpr):
            return self._infer_binary_type(expr)
        elif isinstance(expr, CastExpr):
            return expr.target_type
        elif isinstance(expr, UnaryExpr):
            operand_type = self._infer_type(expr.operand)
            if operand_type is None:
                return None
            if expr.op == "&":
                if isinstance(expr.operand, Identifier) and expr.operand.name in self.function_table:
                    return operand_type
                from ..type_composition import add_outer_pointer

                return add_outer_pointer(operand_type, clear_array=True)
            if expr.op == "*":
                if operand_type.is_array:
                    from ..type_composition import strip_outer_storage

                    return strip_outer_storage(operand_type, array=True)
                if operand_type.pointer_depth > 0:
                    from ..type_composition import strip_outer_storage

                    return strip_outer_storage(operand_type)
            if expr.op == "!":
                return TypeExpr(base="bool")
            overloaded = self._operator_return_type(operand_type, expr.op, unary=True)
            if overloaded is not None:
                return overloaded
            return operand_type
        elif isinstance(expr, TernaryExpr):
            return self._infer_ternary_type(expr)
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
                    return self._collection_literal_type("Vector", [elem_type])
            return self._collection_literal_type("Vector", [TypeExpr(base="int")])
        elif isinstance(expr, MapLiteral):
            if expr.entries:
                key_type = self._infer_type(expr.entries[0].key)
                val_type = self._infer_type(expr.entries[0].value)
                if key_type and val_type:
                    return self._collection_literal_type("Map", [key_type, val_type])
            return self._collection_literal_type("Map", [TypeExpr(base="string"), TypeExpr(base="int")])
        elif isinstance(expr, SpawnExpr):
            ret_type = self._infer_spawn_return_type(expr.fn)
            return TypeExpr(base="Thread", generic_args=[ret_type])
        elif isinstance(expr, BraceInitializer):
            if expr.elements:
                first_type = self._infer_type(expr.elements[0])
                return first_type
            return None
        return None

    def _infer_field_access_type(self, expr):
        if isinstance(expr.obj, Identifier):
            enum_values = self.enum_table.get(expr.obj.name)
            if enum_values is not None and expr.field in enum_values:
                return TypeExpr(base=expr.obj.name or "int")
            class_info = self.class_table.get(expr.obj.name) if self.scope.lookup(expr.obj.name) is None else None
            if class_info and expr.field in class_info.static_fields:
                return class_info.static_fields[expr.field].type
        obj_type = self._infer_type(expr.obj)
        if obj_type and (obj_type.base == "Tuple" or obj_type.base.startswith("(")):
            if expr.field.startswith("_") and expr.field[1:].isdigit():
                index = int(expr.field[1:])
                if expr.field == f"_{index}" and index < len(obj_type.generic_args):
                    return obj_type.generic_args[index]
            return None
        if obj_type and obj_type.base in self.rich_enum_table:
            if expr.field == "tag":
                return TypeExpr(base="int")
            return None
        if obj_type and obj_type.base in {"Array", "List", "Map", "Set", "Vector"}:
            if expr.field in {"len", "length", "size"}:
                return TypeExpr(base="int", is_const=obj_type.is_const)
        if isinstance(expr.obj, FieldAccessExpr) and isinstance(expr.obj.obj, FieldAccessExpr):
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
            is_property = False
            if expr.field in cls.properties:
                field_type = cls.properties[expr.field].type
                is_property = True
            elif expr.field in cls.fields:
                field_type = cls.fields[expr.field].type
            if field_type and cls.generic_params and obj_type.generic_args:
                subs = dict(zip(cls.generic_params, obj_type.generic_args))
                field_type = self._substitute_type(field_type, subs)
            return self._const_member_type(obj_type, field_type, is_property)
        if obj_type:
            struct_name = obj_type.base.removeprefix("struct ")
            struct_decl = self.struct_table.get(struct_name)
            if struct_decl:
                field_type = next(
                    (field.type for field in struct_decl.fields if field.name == expr.field),
                    None,
                )
                return self._const_member_type(obj_type, field_type)
        return None

    @staticmethod
    def _const_member_type(receiver_type, field_type, is_property=False):
        if (
            field_type is not None
            and receiver_type.is_const
            and not is_property
            and field_type.pointer_depth == 0
            and field_type.base != "string"
        ):
            return replace(field_type, is_const=True)
        return field_type
