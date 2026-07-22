"""Typed source-call signature validation."""

from ..ast_nodes import BraceInitializer, ListLiteral


class CallSignatureContractsMixin:
    def _validate_call_signature(
        self,
        name,
        params,
        args,
        arg_names,
        line,
        col,
        substitutions=None,
        unresolved=(),
        gpu_dispatch=False,
        declaration=None,
        bodyless_ffi=False,
    ):
        names = self._arg_names(args, arg_names)
        self._validate_call_arity(name, params, args, names, line, col)
        transferred = frozenset()
        if declaration is not None:
            from ..ir.gen.call_effects import owned_transfer_param_indices

            transferred = owned_transfer_param_indices(declaration)
        for param_index, arg_index in self._bound_arguments(params, names):
            if arg_index >= len(args):
                continue
            expected = params[param_index].type
            if substitutions:
                expected = self._substitute_type(expected, substitutions)
            if expected.base in unresolved:
                continue
            gpu_array_parameter = bool(
                gpu_dispatch and (canonical_expected := self._canonical_type(expected)) and canonical_expected.is_array
            )
            argument = args[arg_index]
            if isinstance(argument, (BraceInitializer, ListLiteral)):
                self._validate_array_object_initializer(
                    expected,
                    argument,
                    f"Argument '{params[param_index].name}' to '{name}()'",
                    getattr(argument, "line", line),
                    getattr(argument, "col", col),
                )
            if not gpu_array_parameter:
                expected = self._array_parameter_initializer_type(expected, argument)
            self._validate_opaque_call_argument(
                declaration,
                param_index,
                expected,
                argument,
                name,
                bodyless_ffi=bodyless_ffi,
            )
            self._validate_volatile_reference_conversion(
                expected,
                argument,
                f"Argument '{params[param_index].name}' to '{name}()'",
                getattr(argument, "line", line),
                getattr(argument, "col", col),
            )
            argument_line = getattr(argument, "line", line)
            argument_col = getattr(argument, "col", col)
            # A raw C string may cross a proven borrow-only ``string``
            # parameter ephemerally.  Only a retaining/consuming boundary
            # stores the value and therefore requires owned provenance.
            if params[param_index].keep or param_index in transferred:
                self._validate_managed_string_source(
                    expected,
                    argument,
                    f"Argument '{params[param_index].name}' to '{name}()'",
                    argument_line,
                    argument_col,
                )
            self._contextualize_generic_constructor(expected, argument)
            self._contextualize_aggregate_initializer(
                expected,
                argument,
                f"Argument '{params[param_index].name}' to '{name}()'",
                argument_line,
                argument_col,
            )
            if self._validate_callable_value(
                expected,
                argument,
                argument_line,
                argument_col,
            ):
                continue
            actual = self._infer_type(argument)
            if actual and gpu_array_parameter:
                if not self._array_target_has_capacity(argument, actual):
                    self._error(
                        f"Argument '{params[param_index].name}' to '{name}()' "
                        "has no provable readable GPU buffer capacity",
                        argument_line,
                        argument_col,
                    )
                elif not self._gpu_input_has_compatible_storage(argument, expected, actual):
                    self._error(
                        f"Argument '{params[param_index].name}' to '{name}()' "
                        "does not have an ABI-compatible GPU buffer element type",
                        argument_line,
                        argument_col,
                    )
                continue
            compatible = actual and self._types_compatible(expected, actual)
            if actual and not compatible:
                self._error(
                    f"Argument '{params[param_index].name}' to '{name}()' "
                    f"expects '{self._format_type(expected)}' but got "
                    f"'{self._format_type(actual)}'",
                    argument_line,
                    argument_col,
                )


__all__ = ["CallSignatureContractsMixin"]
