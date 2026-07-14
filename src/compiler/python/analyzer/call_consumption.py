"""Ownership-transfer contracts for consuming call parameters."""


class CallConsumptionContractsMixin:
    def _validate_consuming_arguments(
        self,
        declaration,
        args,
        arg_names,
        label,
    ) -> None:
        from ..ownership_effects import owned_transfer_param_indices

        transferred = owned_transfer_param_indices(declaration)
        if not transferred:
            return
        names = self._arg_names(args, arg_names)
        supplied = set()
        for parameter_index, argument_index in self._bound_arguments(
            declaration.params,
            names,
        ):
            supplied.add(parameter_index)
            if parameter_index not in transferred or argument_index >= len(args):
                continue
            argument = args[argument_index]
            if not self._argument_produces_owned_result(argument):
                self._error(
                    f"Argument to consuming parameter "
                    f"'{declaration.params[parameter_index].name}' of "
                    f"'{label}()' must be a fresh caller-owned managed value",
                    getattr(argument, "line", 0),
                    getattr(argument, "col", 0),
                )
        for parameter_index in transferred - supplied:
            parameter = declaration.params[parameter_index]
            if parameter.default is None or not self._argument_produces_owned_result(parameter.default):
                self._error(
                    f"Default for consuming parameter '{parameter.name}' of "
                    f"'{label}()' must produce a fresh managed value",
                    parameter.line,
                    parameter.col,
                )


__all__ = ["CallConsumptionContractsMixin"]
