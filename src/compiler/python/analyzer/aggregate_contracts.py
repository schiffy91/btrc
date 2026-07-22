"""Semantic contracts for native aggregate values."""


class AggregateContractsMixin:
    def _validate_tuple_field_access(self, expression, object_type) -> bool:
        """Validate and recognize the canonical zero-based tuple field API."""
        canonical = self._canonical_type(object_type)
        if canonical is None or not (canonical.base == "Tuple" or canonical.base.startswith("(")):
            return False
        suffix = expression.field[1:] if expression.field.startswith("_") else ""
        if not suffix.isdigit() or expression.field != f"_{int(suffix)}":
            self.context.error(
                f"Tuple has no field '{expression.field}'; use '_N' for a zero-based element index",
                expression.line,
                expression.col,
            )
            return True
        index = int(suffix)
        if index >= len(canonical.generic_args):
            self.context.error(
                f"Tuple field '{expression.field}' is out of range for {len(canonical.generic_args)} element(s)",
                expression.line,
                expression.col,
            )
        return True

    def _validate_struct_field_access(self, expression, object_type) -> bool:
        """Validate a member access when its receiver is a known C struct."""
        canonical = self._canonical_type(object_type)
        if canonical is None:
            return False
        struct_name = canonical.base.removeprefix("struct ")
        declaration = self.declarations.struct_table.get(struct_name)
        if declaration is None:
            return False
        if not any(field.name == expression.field for field in declaration.fields):
            self.context.error(
                f"Struct '{struct_name}' has no field '{expression.field}'",
                expression.line,
                expression.col,
            )
        return True


__all__ = ["AggregateContractsMixin"]
