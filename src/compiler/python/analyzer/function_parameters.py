"""Callable parameter symbols and declaration-order contracts."""

from .core import SymbolInfo


class FunctionParameterContractsMixin:
    def _param_symbol(self, param) -> SymbolInfo:
        """Build a parameter symbol using its represented runtime value."""
        value_type = (
            param.type if self.in_gpu_function and param.type.is_array else self._array_parameter_value_type(param.type)
        )
        return self._local_symbol(
            param.name,
            value_type,
            "param",
            param.name_line or param.line,
            param.name_col or param.col,
        )

    def _validate_default_params(self, params, line, col) -> None:
        """Ensure default parameters follow all required parameters."""
        seen_default = False
        for param in params:
            if param.default is not None:
                seen_default = True
            elif seen_default:
                self._error(
                    f"Non-default parameter '{param.name}' follows default parameter",
                    param.line or line,
                    param.col or col,
                )
                break


__all__ = ["FunctionParameterContractsMixin"]
