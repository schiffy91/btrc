"""Return-type inference for functions, methods, and C interop calls."""

from dataclasses import replace

from ..ast_nodes import FieldAccessExpr, Identifier, LambdaExpr, TypeExpr
from ..gpu_builtins import WGSL_SAME_TYPE_BUILTINS
from ..hosted_abi import hosted_semantic_result
from ..operator_semantics import GENERIC_COMPARISON_INTRINSICS
from .c_call_types import C_POINTER_CALL_RESULTS, C_SCALAR_CALL_RESULTS
from .gpu_type_contracts import gpu_builtin_call_uses_intrinsic


class CallTypeInferenceMixin:
    def _infer_call_type(self, expr):
        if isinstance(expr.callee, LambdaExpr):
            callable_type = self._infer_type(expr.callee)
            if callable_type and callable_type.generic_args:
                return callable_type.generic_args[0]
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            symbol = self.scope.lookup(name)
            signature = self._function_pointer_signature(symbol.type if symbol else None)
            if signature is not None:
                return signature[0]
            if symbol is not None and symbol.kind != "function":
                return None
            if gpu_builtin_call_uses_intrinsic(self, expr):
                if name in WGSL_SAME_TYPE_BUILTINS and expr.args:
                    return self._infer_type(expr.args[0])
                return TypeExpr(base="float")
            # Exact hosted semantics take precedence over an authenticated
            # bodyless source prototype.  The source spelling may use
            # ``string`` for C compatibility, while the registry must expose
            # a raw alias so ownership conversion happens at the call site.
            if self._hosted_call_uses_owned_symbol(expr):
                result = hosted_semantic_result(name)
                if result is not None:
                    return result
            if name in self.declarations.function_table:
                return self.declarations.function_table[name].return_type
            if name == "Mutex" and expr.args:
                argument_type = self._infer_type(expr.args[0])
                return TypeExpr(
                    base="Mutex",
                    generic_args=[argument_type or TypeExpr(base="int")],
                )
            if name in self.declarations.class_table:
                return self._infer_constructor_call_type(expr, self.declarations.class_table[name])
            if name == "len":
                return TypeExpr(base="int")
            if name == "print":
                return TypeExpr(base="void")
            if name in C_SCALAR_CALL_RESULTS:
                return TypeExpr(base=C_SCALAR_CALL_RESULTS[name])
            if name in C_POINTER_CALL_RESULTS:
                base, depth = C_POINTER_CALL_RESULTS[name]
                return TypeExpr(base=base, pointer_depth=depth)
            hosted_result = hosted_semantic_result(name)
            if hosted_result is not None:
                return hosted_result
            if name in GENERIC_COMPARISON_INTRINSICS:
                return TypeExpr(base="bool")
            if name == "__btrc_hash":
                return TypeExpr(base="uint")
            if name == "gpu_id":
                return TypeExpr(base="int")
        if isinstance(expr.callee, FieldAccessExpr):
            result = self._infer_method_call_type(expr)
            if expr.callee.optional and result is not None and self._is_pointer_value(result):
                return replace(result, is_nullable=True)
            return result
        signature = self._function_pointer_signature(self._infer_type(expr.callee))
        if signature is not None:
            return signature[0]
        return None

    def _infer_method_call_type(self, expr):
        callee = expr.callee
        if isinstance(callee.obj, Identifier) and callee.obj.name in self.declarations.rich_enum_table:
            enum_decl = self.declarations.rich_enum_table[callee.obj.name]
            if any(variant.name == callee.field for variant in enum_decl.variants):
                return TypeExpr(base=enum_decl.name)
        signature = self._function_pointer_signature(self._infer_type(callee))
        if signature is not None:
            return signature[0]
        object_type = self._infer_type(callee.obj)
        if (
            object_type
            and (
                object_type.base in self._NUMERIC_TYPES
                or object_type.base == "bool"
                or object_type.base in self.declarations.enum_table
                or object_type.base in self.declarations.rich_enum_table
            )
            and object_type.pointer_depth == 0
            and not object_type.is_array
            and not object_type.generic_args
            and callee.field == "toString"
        ):
            return TypeExpr(base="string")
        if object_type and (
            object_type.base == "string" or (object_type.base == "char" and object_type.pointer_depth >= 1)
        ):
            return self._string_method_return_type(callee.field)
        if object_type and object_type.base == "Thread" and object_type.generic_args and callee.field == "join":
            return object_type.generic_args[0]
        if object_type and object_type.base == "Mutex" and object_type.generic_args:
            if callee.field == "get":
                return object_type.generic_args[0]
            if callee.field in ("set", "destroy"):
                return TypeExpr(base="void")
        if object_type and object_type.base in {"Array", "List", "Map", "Set", "Vector"} and callee.field == "size":
            return TypeExpr(base="int")
        if object_type and object_type.base in self.declarations.class_table:
            cls = self.declarations.class_table[object_type.base]
            method = cls.methods.get(callee.field)
            if method is not None:
                substitutions = {}
                if cls.generic_params and object_type.generic_args:
                    substitutions.update(zip(cls.generic_params, object_type.generic_args))
                if method.generic_params:
                    inferred = self._infer_method_type_args(expr, method, substitutions)
                    if inferred:
                        substitutions.update(inferred)
                if substitutions:
                    return self._substitute_type(method.return_type, substitutions)
                return method.return_type
        if (
            isinstance(callee.obj, Identifier)
            and self.scope.lookup(callee.obj.name) is None
            and callee.obj.name in self.declarations.class_table
        ):
            method = self.declarations.class_table[callee.obj.name].methods.get(callee.field)
            if method is not None:
                return method.return_type
        return None
