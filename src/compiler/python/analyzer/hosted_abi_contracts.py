"""Call-site semantic validation for the hosted C ABI."""

from __future__ import annotations

from ..ast_nodes import CallExpr, CastExpr, Identifier
from ..hosted_abi import (
    DEALLOC_FREE,
    RETURN_FRESH,
    hosted_alias_argument_is_provably_null,
    hosted_function,
    hosted_function_owned_name,
    hosted_owned_name,
    hosted_return_deallocator,
    hosted_return_effect,
    hosted_source_helper_adopts_raw_string,
)


class HostedAbiContractsMixin:
    def _hosted_call_bypasses_source_definition(self, call) -> bool:
        """Keep canonical stdlib internals bound to libc under user shadowing."""
        if not isinstance(call.callee, Identifier):
            return False
        return self._hosted_name_bypasses_source_definition(call.callee.name)

    def _hosted_name_bypasses_source_definition(self, name: str) -> bool:
        declaration = self.declarations.function_table.get(name)
        if declaration is None or declaration.body is None:
            return False
        if not hosted_owned_name(name):
            return False
        return self._hosted_stdlib_source(self.current_source_file) and not self._hosted_stdlib_source(
            getattr(declaration, "source_file", None)
        )

    def _hosted_call_uses_owned_symbol(self, call, *, local_names=None) -> bool:
        if not isinstance(call.callee, Identifier):
            return False
        return self._hosted_name_uses_owned_symbol(
            call.callee.name,
            local_names=local_names,
        )

    def _hosted_name_uses_owned_symbol(self, name: str, *, local_names=None) -> bool:
        if not hosted_owned_name(name):
            return False
        if local_names is None:
            symbol = self.scope.lookup(name)
            if symbol is not None and symbol.kind != "function":
                return False
        elif name in local_names:
            return False
        declaration = self.declarations.function_table.get(name)
        return bool(
            declaration is None or declaration.body is None or self._hosted_name_bypasses_source_definition(name)
        )

    def _hosted_function_value_uses_owned_symbol(self, name: str) -> bool:
        return hosted_function_owned_name(name) and self._hosted_name_uses_owned_symbol(name)

    def _validate_hosted_abi_call(self, call) -> bool:
        """Validate direct calls whose declaration comes from a hosted header."""
        if not self._hosted_call_uses_owned_symbol(call):
            return False
        name = call.callee.name
        self._hosted_call_ids.add(id(call))
        if name == "assert":
            if any(call.arg_names or ()) or len(call.args) != 1:
                self._error("'assert()' expects exactly 1 positional argument", call.line, call.col)
            return True

        spec = hosted_function(name)
        if spec is None or spec.parameters is None:
            for argument in call.args:
                if self._expression_is_opaque_borrow(argument):
                    self._error(
                        f"Argument to hosted function '{name}()' cannot forward a "
                        "managed value as a raw representation because its ABI "
                        "effect is not proven read-only",
                        getattr(argument, "line", call.line),
                        getattr(argument, "col", call.col),
                    )
            return self.declarations.function_table.get(name) is None
        if any(call.arg_names or ()):
            self._error(
                f"Hosted function '{name}()' does not accept named arguments",
                call.line,
                call.col,
            )
            return True
        expected_count = len(spec.parameters)
        valid_arity = len(call.args) >= expected_count if spec.variadic else len(call.args) == expected_count
        if not valid_arity:
            qualifier = "at least " if spec.variadic else ""
            self._error(
                f"'{name}()' expects {qualifier}{expected_count} argument(s) but got {len(call.args)}",
                call.line,
                call.col,
            )
            return True

        for index, (argument, expected_shape) in enumerate(zip(call.args, spec.parameters)):
            expected = expected_shape.as_type_expr()
            self._validate_opaque_call_argument(
                None,
                index,
                expected,
                argument,
                name,
                bodyless_ffi=True,
            )
            self._validate_volatile_reference_conversion(
                expected,
                argument,
                f"Argument {index + 1} to hosted function '{name}()'",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            actual = self._infer_type(argument)
            if (
                actual is not None
                and not self._hosted_argument_type_is_deferred(expected, actual)
                and not self._types_compatible(expected, actual)
            ):
                self._error(
                    f"Argument {index + 1} to hosted function '{name}()' "
                    f"expects '{self._format_type(expected)}' but got "
                    f"'{self._format_type(actual)}'",
                    getattr(argument, "line", call.line),
                    getattr(argument, "col", call.col),
                )
            self._validate_source_helper_consumer(call, index, argument)
        return True

    def _hosted_argument_type_is_deferred(self, expected, actual) -> bool:
        canonical = self._canonical_type(actual)
        if canonical is None:
            return True
        if canonical.base in self._active_storage_type_parameters():
            return True
        return bool(
            expected.base == "void"
            and expected.pointer_depth == 1
            and (canonical.base == "string" or canonical.pointer_depth > 0 or canonical.is_array)
        )

    def _validate_source_helper_consumer(self, call, index, argument) -> None:
        name = call.callee.name
        if not hosted_source_helper_adopts_raw_string(name, index):
            return
        if self._raw_lifetime_uses_static_string(argument):
            self._error(
                f"{name}() cannot adopt static string storage; pass fresh raw heap storage",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            return
        managed = self._opaque_managed_origin_type(argument)
        if managed is not None:
            self._error(
                f"{name}() cannot adopt an already-managed value of type "
                f"'{self._format_type(managed)}'; pass fresh raw heap storage",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            return
        producer = argument
        while isinstance(producer, CastExpr):
            producer = producer.expr
        if not isinstance(producer, CallExpr) or not isinstance(
            producer.callee,
            Identifier,
        ):
            return
        if not self._hosted_call_uses_owned_symbol(producer):
            return
        producer_name = producer.callee.name
        alias_is_null = hosted_alias_argument_is_provably_null(
            producer_name,
            producer.args,
        )
        effect = hosted_return_effect(
            producer_name,
            alias_argument_is_null=alias_is_null,
        )
        deallocator = hosted_return_deallocator(
            producer_name,
            alias_argument_is_null=alias_is_null,
        )
        if effect == RETURN_FRESH and deallocator == DEALLOC_FREE:
            return
        self._error(
            f"{name}() cannot adopt storage returned by "
            f"{producer_name}() because it is not proven fresh "
            "free-compatible allocation",
            getattr(argument, "line", call.line),
            getattr(argument, "col", call.col),
        )


__all__ = ["HostedAbiContractsMixin"]
