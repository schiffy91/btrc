"""Semantic signatures for methods implemented directly by the runtime."""

from __future__ import annotations

from ..ast_nodes import Identifier, TypeExpr
from ..string_methods import STRING_METHODS
from ..type_identity import is_semantic_scalar_string


class BuiltinCallValidationMixin:
    def _validate_builtin_method_call(self, expression, receiver_type) -> bool:
        callee = expression.callee
        if isinstance(callee.obj, Identifier) and callee.obj.name in self.rich_enum_table:
            self._validate_rich_enum_constructor(expression)
            return True
        if isinstance(callee.obj, Identifier) and callee.obj.name in self.class_table:
            return False

        receiver_type = self._canonical_type(receiver_type)
        if is_semantic_scalar_string(receiver_type):
            spec = STRING_METHODS.get(callee.field)
            if spec is None:
                self._error(
                    f"String has no method '{callee.field}'",
                    expression.line,
                    expression.col,
                )
            else:
                expected = [TypeExpr(base=name) for name in spec.argument_types]
                self._validate_builtin_signature(f"String.{callee.field}", expected, expression)
            return True

        if receiver_type and receiver_type.base == "Thread":
            if callee.field == "join":
                self._validate_builtin_signature("Thread.join", [], expression)
                self._validate_thread_join_receiver(expression)
            else:
                self._error(
                    f"Thread<T> has no method '{callee.field}'",
                    expression.line,
                    expression.col,
                )
            return True

        if receiver_type and receiver_type.base == "Mutex":
            signatures = {
                "get": [],
                "destroy": [],
                "set": list(receiver_type.generic_args[:1]),
            }
            if callee.field in signatures:
                self._validate_builtin_signature(
                    f"Mutex.{callee.field}",
                    signatures[callee.field],
                    expression,
                )
            else:
                self._error(
                    f"Mutex<T> has no method '{callee.field}'",
                    expression.line,
                    expression.col,
                )
            return True

        if self._is_builtin_scalar_receiver(receiver_type):
            if callee.field != "toString":
                self._error(
                    f"Type '{self._format_type(receiver_type)}' has no method '{callee.field}'",
                    expression.line,
                    expression.col,
                )
            else:
                self._validate_builtin_signature(
                    f"{self._format_type(receiver_type)}.toString",
                    [],
                    expression,
                )
            return True
        return False

    def _is_builtin_scalar_receiver(self, type_expr) -> bool:
        return bool(
            type_expr
            and (type_expr.base in self._NUMERIC_TYPES or type_expr.base == "bool" or type_expr.base in self.enum_table)
            and type_expr.pointer_depth == 0
            and not type_expr.is_array
            and not type_expr.generic_args
        )

    def _validate_builtin_signature(self, name, expected_types, expression):
        if any(expression.arg_names or []):
            self._error(
                f"'{name}()' does not accept named arguments",
                expression.line,
                expression.col,
            )
        if len(expression.args) != len(expected_types):
            self._error(
                f"'{name}()' expects {len(expected_types)} argument(s) but got {len(expression.args)}",
                expression.line,
                expression.col,
            )
        for index, (expected, argument) in enumerate(zip(expected_types, expression.args), 1):
            actual = self._infer_type(argument)
            if actual and not self._types_compatible(expected, actual):
                self._error(
                    f"Argument {index} to '{name}()' expects "
                    f"'{self._format_type(expected)}' but got "
                    f"'{self._format_type(actual)}'",
                    getattr(argument, "line", expression.line),
                    getattr(argument, "col", expression.col),
                )

    def _validate_rich_enum_constructor(self, expression):
        callee = expression.callee
        enum_decl = self.rich_enum_table[callee.obj.name]
        variant = next(
            (item for item in enum_decl.variants if item.name == callee.field),
            None,
        )
        if variant is None:
            self._error(
                f"Rich enum '{enum_decl.name}' has no variant '{callee.field}'",
                expression.line,
                expression.col,
            )
            return
        self._validate_call_signature(
            f"{enum_decl.name}.{variant.name}",
            variant.params,
            expression.args,
            expression.arg_names,
            expression.line,
            expression.col,
        )
