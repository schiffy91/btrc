"""Strict declaration-shape contracts for emitted C callables."""

from dataclasses import replace

from ..type_identity import type_shape_key
from .semantic_keys import semantic_ast_key

MAGIC_METHOD_SIGNATURES = {
    "__add__": (1, None),
    "__sub__": (1, None),
    "__mul__": (1, None),
    "__div__": (1, None),
    "__mod__": (1, None),
    "__eq__": (1, "bool"),
    "__ne__": (1, "bool"),
    "__lt__": (1, "bool"),
    "__gt__": (1, "bool"),
    "__le__": (1, "bool"),
    "__ge__": (1, "bool"),
    "__neg__": (0, None),
    "toString": (0, "string"),
    "__del__": (0, "void"),
}


def is_magic_method_name(name: str) -> bool:
    """Whether a source method spelling has compiler-defined lowering."""
    return name in MAGIC_METHOD_SIGNATURES


class DeclarationContractsMixin:
    def _validate_array_return_declaration(self, declaration, owner=None) -> None:
        """Only GPU kernels may use btrc's array-return syntax."""
        return_type = declaration.return_type
        if not return_type or not return_type.is_array or getattr(declaration, "is_gpu", False):
            return
        subject = f"Method '{owner}.{declaration.name}'" if owner else f"Function '{declaration.name}'"
        self._error(
            f"{subject} cannot return an array outside @gpu",
            declaration.line,
            declaration.col,
        )

    def _validate_class_callable_shape(self, class_decl, method) -> None:
        owner = f"method '{class_decl.name}.{method.name}'"
        if class_decl.generic_params and method.access == "class":
            self._error(
                f"Static {owner} has no specialization target and is not supported on a generic class",
                method.line,
                method.col,
            )
        if method.is_constructor:
            self._validate_constructor_shape(class_decl, method)
            return
        if method.name == class_decl.name:
            message = (
                f"Constructor '{class_decl.name}' cannot have return type '{method.return_type.base}'"
                if method.return_type.base != class_decl.name
                else f"Method '{class_decl.name}.{method.name}' uses explicit-return constructor syntax"
            )
            self._error(message, method.line, method.col)
        if method.is_abstract:
            if not class_decl.is_abstract:
                self._error(
                    f"Abstract {owner} requires an abstract class",
                    method.line,
                    method.col,
                )
            if method.body is not None:
                self._error(f"Abstract {owner} cannot have a body", method.line, method.col)
        elif method.body is None:
            self._error(f"Concrete {owner} requires a body", method.line, method.col)

        signature = MAGIC_METHOD_SIGNATURES.get(method.name)
        if signature is None:
            return
        arity, return_base = signature
        if method.access == "class":
            self._error(f"Magic {owner} must be an instance method", method.line, method.col)
        if method.is_abstract or method.body is None:
            self._error(f"Magic {owner} requires a concrete body", method.line, method.col)
        if method.generic_params:
            self._error(f"Magic {owner} cannot be generic", method.line, method.col)
        if len(method.params) != arity:
            self._error(
                f"Magic {owner} expects {arity} explicit parameter(s) but got {len(method.params)}",
                method.line,
                method.col,
            )
        canonical_return = self._canonical_type(method.return_type)
        if return_base and (
            canonical_return is None
            or canonical_return.base != return_base
            or canonical_return.pointer_depth
            or canonical_return.is_array
            or canonical_return.generic_args
        ):
            self._error(
                f"Magic {owner} must return '{return_base}'",
                method.line,
                method.col,
            )

    def _validate_constructor_shape(self, class_decl, method) -> None:
        owner = f"Constructor '{class_decl.name}'"
        if method.access == "class":
            self._error(f"{owner} cannot be class/static", method.line, method.col)
        if method.is_abstract:
            self._error(f"{owner} cannot be abstract", method.line, method.col)
        if method.is_gpu:
            self._error(f"{owner} cannot be @gpu", method.line, method.col)
        if method.keep_return:
            self._error(f"{owner} cannot use keep-return", method.line, method.col)
        if method.body is None:
            self._error(f"{owner} requires a concrete body", method.line, method.col)
        if method.generic_params:
            self._error(f"{owner} cannot be generic", method.line, method.col)

    def _function_declarations_compatible(self, left, right) -> bool:
        if (
            self._function_linkage(left) != self._function_linkage(right)
            or self._function_type_key(left.return_type) != self._function_type_key(right.return_type)
            or left.is_gpu != right.is_gpu
            or left.keep_return != right.keep_return
            or len(left.params) != len(right.params)
        ):
            return False
        for first, second in zip(left.params, right.params):
            if (
                first.name != second.name
                or first.keep != second.keep
                or type_shape_key(first.type) != type_shape_key(second.type)
                or not self._compatible_defaults(first.default, second.default)
            ):
                return False
        return True

    @staticmethod
    def _compatible_defaults(left, right) -> bool:
        return left is None or right is None or semantic_ast_key(left) == semantic_ast_key(right)

    @staticmethod
    def _function_linkage(declaration) -> str:
        return "internal" if declaration.return_type.is_static else "external"

    @staticmethod
    def _function_type_key(type_expr):
        return type_shape_key(replace(type_expr, is_extern=False, is_static=False))

    @staticmethod
    def _merge_function_defaults(definition, declaration) -> None:
        for target, source in zip(definition.params, declaration.params):
            if target.default is None and source.default is not None:
                target.default = source.default

    def _validate_main_signature(self, function) -> None:
        if function.name != "main":
            return
        result = self._canonical_type(function.return_type)
        valid_result = bool(
            result
            and result.base in {"int", "void"}
            and result.pointer_depth == 0
            and not result.is_array
            and not result.generic_args
        )
        valid_params = not function.params
        if result and result.base == "int" and len(function.params) == 2:
            argc = self._canonical_type(function.params[0].type)
            argv = self._canonical_type(function.params[1].type)
            argv_depth = argv.pointer_depth + int(argv.is_array) if argv else -1
            valid_params = bool(
                argc
                and argc.base == "int"
                and argc.pointer_depth == 0
                and not argc.is_array
                and argv
                and argv.base == "char"
                and argv_depth == 2
            )
        if not valid_result or not valid_params or function.is_gpu:
            self._error(
                "main must be 'int main()', 'int main(int, char**)', or 'void main()'",
                function.line,
                function.col,
            )

    @staticmethod
    def _type_without_extern(type_expr):
        return replace(type_expr, is_extern=False)


__all__ = [
    "MAGIC_METHOD_SIGNATURES",
    "DeclarationContractsMixin",
    "is_magic_method_name",
]
