"""Closure-value boundaries for the plain ``__fn_ptr`` ABI."""

from dataclasses import replace

from ..ast_nodes import (
    BraceInitializer,
    Identifier,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    TupleLiteral,
)


class CallableValueValidationMixin:
    """Reject environment-bearing callables where C stores only a function."""

    _SEQUENCE_LITERAL_TYPES = frozenset(("Array", "List", "Set", "Vector"))

    def _function_pointer_signature(self, type_expr):
        """Return the canonical ``(return, params...)`` callable shape."""
        canonical = self._canonical_type(type_expr)
        if (
            canonical is None
            or canonical.base != "__fn_ptr"
            or canonical.pointer_depth != 0
            or canonical.is_array
            or not canonical.generic_args
        ):
            return None
        return canonical.generic_args

    def _captures_environment(self, expression) -> bool:
        if isinstance(expression, LambdaExpr):
            return bool(expression.captures)
        if isinstance(expression, Identifier):
            symbol = self.scope.lookup(expression.name)
            return bool(symbol and symbol.captures_environment)
        return False

    def _validate_callable_storage(self, type_expr, initializer, explicit_type, line, col) -> bool:
        allow_direct_local = not explicit_type and isinstance(initializer, LambdaExpr)
        return self._validate_callable_value(
            type_expr,
            initializer,
            line,
            col,
            allow_direct_local=allow_direct_local,
        )

    def _validate_callable_value(self, expected, value, line, col, *, allow_direct_local=False) -> bool:
        """Report one diagnostic when ``value`` would erase a closure env.

        Composite literals are checked against their contextual element types,
        which closes inferred and explicitly typed nested collection escapes.
        The boolean result lets callers suppress secondary type diagnostics at
        the same source site.
        """
        if allow_direct_local and isinstance(value, LambdaExpr):
            return False
        if not self._callable_value_escapes(expected, value):
            return False
        self._error(
            "A capturing lambda cannot escape through a bare __fn_ptr; a closure value is required",
            line,
            col,
        )
        return True

    def _callable_value_escapes(self, expected, value) -> bool:
        if expected is None or value is None:
            return False
        expected = self._canonical_type(expected)
        if self._function_pointer_signature(expected) is not None:
            return self._captures_environment(value)

        if isinstance(value, (ListLiteral, BraceInitializer)):
            element_type = self._sequence_element_type(expected)
            return bool(element_type) and any(
                self._callable_value_escapes(element_type, element) for element in value.elements
            )

        if isinstance(value, MapLiteral) and expected.base == "Map" and len(expected.generic_args) == 2:
            key_type, value_type = expected.generic_args
            return any(
                self._callable_value_escapes(key_type, entry.key)
                or self._callable_value_escapes(value_type, entry.value)
                for entry in value.entries
            )

        if isinstance(value, TupleLiteral) and expected.base == "Tuple":
            return any(
                self._callable_value_escapes(item_type, item)
                for item_type, item in zip(expected.generic_args, value.elements)
            )
        return False

    def _validate_fn_ptr_call(self, name, expected_types, args, line, col, arg_names=None):
        if any(arg_names or ()):
            self._error(f"'{name}()' function-pointer calls do not support named arguments", line, col)
        if len(args) != len(expected_types):
            self._error(f"'{name}()' expects {len(expected_types)} argument(s) but got {len(args)}", line, col)
            return
        for index, (expected, arg) in enumerate(zip(expected_types, args), 1):
            self._contextualize_aggregate_initializer(
                expected,
                arg,
                f"Argument {index} to '{name}()'",
                getattr(arg, "line", line),
                getattr(arg, "col", col),
            )
            actual = self._infer_type(arg)
            if actual and not self._types_compatible(expected, actual):
                self._error(
                    f"Argument {index} to '{name}()' expects "
                    f"'{self._format_type(expected)}' but got "
                    f"'{self._format_type(actual)}'",
                    getattr(arg, "line", line),
                    getattr(arg, "col", col),
                )

    def _sequence_element_type(self, expected):
        if expected.is_array:
            return replace(expected, is_array=False, array_size=None)
        if expected.base in self._SEQUENCE_LITERAL_TYPES and len(expected.generic_args) == 1:
            return expected.generic_args[0]
        return None
