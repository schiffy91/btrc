"""Declaration and value contracts for simple enums."""

_C11_INT_MIN = -(2**31)
_C11_INT_MAX = 2**31 - 1


class EnumContractsMixin:
    def _validate_enum_declaration(self, declaration) -> None:
        owner = declaration.name or ""
        prior = set()
        previous = -1
        for value in declaration.values:
            if value.value is not None:
                valid, numeric = self._integer_constant_expression(
                    value.value,
                    enum_owner=owner,
                    allowed_enum_members=prior,
                )
                if not valid:
                    self.context.error(
                        f"Enum value '{value.name}' requires an integral constant expression using only earlier members",
                        value.line,
                        value.col,
                    )
                    numeric = None
                elif numeric is not None and not (_C11_INT_MIN <= numeric <= _C11_INT_MAX):
                    self.context.error(
                        f"Enum value '{value.name}' is outside the strict-C11 int range",
                        value.line,
                        value.col,
                    )
                    numeric = None
            else:
                numeric = previous + 1 if previous is not None else None
                if numeric is not None and not (_C11_INT_MIN <= numeric <= _C11_INT_MAX):
                    self.context.error(
                        f"Implicit enum value '{value.name}' is outside the strict-C11 int range",
                        value.line,
                        value.col,
                    )
                    numeric = None
            self.declarations.enum_constant_values[(owner, value.name)] = numeric
            previous = numeric
            prior.add(value.name)


__all__ = ["EnumContractsMixin"]
