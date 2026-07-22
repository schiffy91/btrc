"""Strict-C subject and case contracts for switch statements."""


class SwitchContractsMixin:
    def _validate_switch_contract(self, statement) -> None:
        subject_type = self._infer_type(statement.value)
        if subject_type is not None and not self._is_integral_value(subject_type):
            self.context.error(
                f"Switch subject must be integral, got '{self._format_type(subject_type)}'",
                statement.line,
                statement.col,
            )

        default_count = 0
        constants: dict[int, object] = {}
        for case in statement.cases:
            if case.value is None:
                default_count += 1
                continue
            case_type = self._infer_type(case.value)
            if case_type is not None and not self._is_integral_value(case_type):
                self.context.error(
                    f"Switch case must be integral, got '{self._format_type(case_type)}'",
                    getattr(case.value, "line", statement.line),
                    getattr(case.value, "col", statement.col),
                )
            valid, numeric = self._integer_constant_expression(case.value)
            if not valid:
                self.context.error(
                    "Switch case requires an integral constant expression",
                    getattr(case.value, "line", statement.line),
                    getattr(case.value, "col", statement.col),
                )
                continue
            if numeric is None:
                continue
            if numeric in constants:
                self.context.error(
                    f"Duplicate switch case value {numeric}",
                    getattr(case.value, "line", statement.line),
                    getattr(case.value, "col", statement.col),
                )
            else:
                constants[numeric] = case
        if default_count > 1:
            self.context.error(
                "Switch cannot contain more than one default case",
                statement.line,
                statement.col,
            )


__all__ = ["SwitchContractsMixin"]
