"""Semantic contracts for implicit target-directed conversions."""


class ConversionContractsMixin:
    def _requires_string_conversion(self, target, source) -> bool:
        """Whether assignment compatibility implies a runtime toString call."""
        target = self._canonical_type(target)
        source = self._canonical_type(source)
        from ..string_conversion import requires_class_to_string

        return requires_class_to_string(
            self.class_table,
            target,
            source,
            canonicalize=self._canonical_type,
        )

    def _validate_operator_argument(
        self,
        expression,
        operator,
        right_type,
        overload,
    ) -> None:
        """Validate an overloaded binary operator's declared RHS contract."""
        method, substitutions = overload
        if not method.params:
            return
        expected = method.params[0].type
        if substitutions:
            expected = self._substitute_type(expected, substitutions)
        if not self._types_compatible(expected, right_type):
            self._error(
                f"Operator '{operator}' expects "
                f"'{self._format_type(expected)}' but got "
                f"'{self._format_type(right_type)}'",
                expression.line,
                expression.col,
            )


__all__ = ["ConversionContractsMixin"]
