"""Resolution contracts for identifiers used as runtime values."""

_KNOWN_C_GLOBALS = frozenset({"stdin", "stdout", "stderr", "errno"})


class IdentifierContractsMixin:
    def _analyze_identifier_value(
        self,
        expression,
        *,
        direct_callee=False,
        qualification_receiver=False,
    ) -> None:
        self._record_lambda_identifier(expression)
        if self.record_occurrences:
            self._record_identifier(expression)

        name = expression.name
        if self.scope.lookup(name) is not None:
            return
        if name in self.function_table:
            return
        if name in self.class_table:
            if direct_callee or qualification_receiver:
                return
            self._error(
                f"Type name '{name}' cannot be used as a runtime value",
                expression.line,
                expression.col,
            )
            return
        if name in self.enum_table or name in self.rich_enum_table:
            if direct_callee or qualification_receiver:
                return
            self._error(
                f"Type name '{name}' cannot be used as a runtime value",
                expression.line,
                expression.col,
            )
            return
        owners = self._enum_member_owners.get(name, set())
        if len(owners) == 1:
            return
        if len(owners) > 1:
            enums = ", ".join(sorted(owner or "<anonymous>" for owner in owners))
            self._error(
                f"Ambiguous enum member '{name}' belongs to {enums}; qualify it",
                expression.line,
                expression.col,
            )
            return
        if name in self._source_macro_names or name in _KNOWN_C_GLOBALS:
            return
        if name.isupper() or name.startswith("__btrc_"):
            return
        if direct_callee:
            return
        self._error(
            f"Unresolved identifier '{name}' used as a value",
            expression.line,
            expression.col,
        )


__all__ = ["IdentifierContractsMixin"]
