"""Semantic validation for type-directed generic magic calls."""

from ..operator_semantics import (
    GENERIC_COMPARISON_INTRINSICS,
    OperatorTypeError,
    comparison_domain,
    hash_domain,
)


class GenericIntrinsicValidationMixin:
    def _validate_generic_intrinsic_call(self, expr):
        name = expr.callee.name
        expected = 1 if name == "__btrc_hash" else 2
        if len(expr.args) != expected:
            self._error(
                f"{name} expects {expected} operand(s), got {len(expr.args)}",
                expr.line,
                expr.col,
            )
            return
        if any(expr.arg_names or []):
            self._error(f"{name} accepts positional operands only", expr.line, expr.col)
            return
        operand_types = [self._canonical_type(self._infer_type(argument)) for argument in expr.args]
        if any(item is None for item in operand_types):
            self._error(
                f"cannot resolve all operand types for {name}",
                expr.line,
                expr.col,
            )
            return
        if any(self._is_active_type_parameter(item) for item in operand_types):
            return
        try:
            self._validate_generic_intrinsic_types(name, operand_types)
        except OperatorTypeError as error:
            self._error(str(error), expr.line, expr.col)

    def _validate_generic_intrinsic_types(self, name, operand_types):
        context = {
            "class_table": self.class_table,
            "interface_table": self.interface_table,
            "enum_names": frozenset(self.enum_table),
        }
        if name in GENERIC_COMPARISON_INTRINSICS:
            comparison_domain(
                GENERIC_COMPARISON_INTRINSICS[name],
                operand_types[0],
                operand_types[1],
                **context,
            )
            return
        hash_domain(operand_types[0], **context)
