"""Call argument binding and arity validation."""


class CallArgumentBindingMixin:
    def _arg_names(self, args, arg_names):
        names = list(arg_names or [])
        while len(names) < len(args):
            names.append("")
        return names

    def _validate_call_arity(self, name, params, args, names, line, col):
        if any(names):
            self._validate_named_call(name, params, args, names, line, col)
            return
        required = sum(1 for param in params if getattr(param, "default", None) is None)
        if len(args) < required:
            self._error(f"'{name}()' expects at least {required} argument(s) but got {len(args)}", line, col)
        elif len(args) > len(params):
            self._error(f"'{name}()' expects at most {len(params)} argument(s) but got {len(args)}", line, col)

    def _validate_named_call(self, name, params, args, names, line, col):
        parameter_names = [param.name for param in params]
        supplied = set()
        positional_index = 0
        saw_named = False
        for argument_name in names:
            if argument_name:
                saw_named = True
                if argument_name not in parameter_names:
                    self._error(f"'{name}()' has no parameter named '{argument_name}'", line, col)
                    continue
                parameter_index = parameter_names.index(argument_name)
                if parameter_index in supplied:
                    self._error(f"'{name}()' got argument '{argument_name}' more than once", line, col)
                supplied.add(parameter_index)
                continue
            if saw_named:
                self._error(f"'{name}()' positional argument follows named argument", line, col)
                continue
            if positional_index >= len(params):
                self._error(f"'{name}()' expects at most {len(params)} argument(s) but got {len(args)}", line, col)
                continue
            supplied.add(positional_index)
            positional_index += 1
        for index, param in enumerate(params):
            if index not in supplied and getattr(param, "default", None) is None:
                self._error(f"'{name}()' missing required argument '{param.name}'", line, col)

    def _bound_arguments(self, params, names):
        parameter_names = [param.name for param in params]
        positional_index = 0
        saw_named = False
        for argument_index, argument_name in enumerate(names):
            if argument_name:
                saw_named = True
                if argument_name in parameter_names:
                    yield parameter_names.index(argument_name), argument_index
                continue
            if saw_named or positional_index >= len(params):
                continue
            yield positional_index, argument_index
            positional_index += 1


__all__ = ["CallArgumentBindingMixin"]
