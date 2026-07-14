"""Semantic contracts for managed parameter ownership transfer."""

from ..ast_nodes import DeleteStmt, Identifier, ReleaseStmt


class ParameterConsumptionContractsMixin:
    def _validate_managed_parameter_consumption(
        self,
        statement,
        expression,
        operand_type,
    ) -> None:
        if (
            not isinstance(statement, (DeleteStmt, ReleaseStmt))
            or not isinstance(expression, Identifier)
            or not self._possibly_managed_parameter_type(operand_type)
        ):
            return
        symbol = self.scope.lookup(expression.name)
        if symbol is None:
            return
        if symbol.kind in {"capture", "lambda_param"} and not symbol.owned_storage:
            self._error(
                "Borrowed managed lambda bindings cannot be released or deleted; bind an owned local first",
                statement.line,
                statement.col,
            )
            return
        if symbol.kind != "param":
            return
        if self.in_virtual_setter or self._is_index_setter_value_param(expression.name):
            self._error(
                "Property/index setter value parameters cannot consume their "
                "argument because assignment results must remain valid",
                statement.line,
                statement.col,
            )
            return
        from ..ownership_effects import owned_transfer_param_indices

        declaration = self.current_callable
        transferred = owned_transfer_param_indices(declaration)
        index = next(
            (
                position
                for position, parameter in enumerate(getattr(declaration, "params", ()))
                if parameter.name == expression.name
            ),
            -1,
        )
        if index not in transferred:
            self._error(
                "Managed parameter consumption must be an unconditional leading "
                "release/delete so callers can prove ownership transfer",
                statement.line,
                statement.col,
            )

    def _possibly_managed_parameter_type(self, type_expr) -> bool:
        if type_expr is None:
            return False
        if type_expr.base == "string" or type_expr.base in self.class_table:
            return True
        params = set(self.current_class.generic_params if self.current_class else ())
        params.update(getattr(self.current_callable, "generic_params", ()) or ())
        return type_expr.base in params

    def _is_index_setter_value_param(self, name: str) -> bool:
        method = self.current_method
        return bool(method and method.name == "set" and len(method.params) == 2 and method.params[1].name == name)


__all__ = ["ParameterConsumptionContractsMixin"]
