"""Resolution contracts for identifiers used as runtime values."""

from .default_argument_contracts import validate_constructor_default_member

_KNOWN_C_GLOBALS = frozenset({"stdin", "stdout", "stderr", "errno", "__func__"})


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
        if self._validate_raw_lifetime_value(expression, direct_callee):
            return
        if not direct_callee and self._hosted_function_value_uses_owned_symbol(name):
            self.context.error(
                f"Hosted function '{name}' cannot be stored or forwarded as a "
                "value because bare __fn_ptr does not preserve its exact C "
                "ABI and effects; call it directly",
                expression.line,
                expression.col,
            )
            return
        if name in self.declarations.function_table:
            return
        if name in self.declarations.class_table:
            if direct_callee or qualification_receiver:
                return
            self.context.error(
                f"Type name '{name}' cannot be used as a runtime value",
                expression.line,
                expression.col,
            )
            return
        if name in self.declarations.enum_table or name in self.declarations.rich_enum_table:
            if direct_callee or qualification_receiver:
                return
            self.context.error(
                f"Type name '{name}' cannot be used as a runtime value",
                expression.line,
                expression.col,
            )
            return
        owners = self.declarations.enum_member_owners.get(name, set())
        if len(owners) == 1:
            return
        if len(owners) > 1:
            enums = ", ".join(sorted(owner or "<anonymous>" for owner in owners))
            self.context.error(
                f"Ambiguous enum member '{name}' belongs to {enums}; qualify it",
                expression.line,
                expression.col,
            )
            return
        if name in self.declarations.source_macro_names or name in _KNOWN_C_GLOBALS:
            return
        if validate_constructor_default_member(
            self,
            expression,
            direct_callee=direct_callee,
        ):
            return
        self._unresolved_c_symbol_reference_ids.add(id(expression))
        if direct_callee:
            self._unresolved_direct_callee_ids.add(id(expression))
        # Resolution is intentionally deferred until all generated-symbol
        # claims (including late generic instances) are known. The final pass
        # preserves the ordinary C-call/macro seams and reports value errors.


__all__ = ["IdentifierContractsMixin"]
