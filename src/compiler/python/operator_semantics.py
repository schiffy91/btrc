"""Shared type-domain rules for comparison and generic hashing operators."""

from __future__ import annotations

from collections.abc import Mapping, Set

from .ast_nodes import TypeExpr
from .numeric_semantics import is_floating_type, is_numeric_type
from .reference_semantics import (
    is_c_string_pointer,
    is_null_type,
    is_reference_type,
    is_scalar_string_type,
    nominally_related,
    reference_types_compatible,
)

COMPARISON_OPERATORS = frozenset(("==", "!=", "<", ">", "<=", ">="))
EQUALITY_OPERATORS = frozenset(("==", "!="))
GENERIC_COMPARISON_INTRINSICS = {
    "__btrc_eq": "==",
    "__btrc_lt": "<",
    "__btrc_gt": ">",
}
GENERIC_INTRINSICS = frozenset((*GENERIC_COMPARISON_INTRINSICS, "__btrc_hash"))

_EMPTY_MAPPING: Mapping[str, object] = {}


class OperatorTypeError(ValueError):
    """A typed operator has no portable meaning for its concrete operands."""


def comparison_domain(
    operator: str,
    left: TypeExpr | None,
    right: TypeExpr | None,
    *,
    class_table: Mapping[str, object] = _EMPTY_MAPPING,
    interface_table: Mapping[str, object] = _EMPTY_MAPPING,
    enum_names: Set[str] = frozenset(),
) -> str:
    """Return ``string``, ``numeric``, or ``reference`` after validation."""
    if operator not in COMPARISON_OPERATORS:
        raise OperatorTypeError(f"unsupported comparison operator '{operator}'")
    if left is None or right is None:
        raise OperatorTypeError(f"cannot resolve operand types for operator '{operator}'")

    left_string = is_scalar_string_type(left)
    right_string = is_scalar_string_type(right)
    if left_string or right_string:
        if (left_string or is_c_string_pointer(left) or is_null_type(left)) and (
            right_string or is_c_string_pointer(right) or is_null_type(right)
        ):
            return "string"
        raise OperatorTypeError(
            f"cannot compare string and non-string operands ('{type_label(left)}' and '{type_label(right)}')"
        )

    if is_numeric_type(left, enum_names) and is_numeric_type(right, enum_names):
        return "numeric"

    left_reference = is_reference_type(left, class_table, interface_table)
    right_reference = is_reference_type(right, class_table, interface_table)
    if left_reference or right_reference:
        if operator not in EQUALITY_OPERATORS:
            raise OperatorTypeError(
                f"operator '{operator}' is not defined for reference operands; only == and != are portable"
            )
        if reference_types_compatible(left, right, class_table, interface_table):
            return "reference"
        if (left.generic_args or right.generic_args) and nominally_related(
            left.base, right.base, class_table, interface_table
        ):
            raise OperatorTypeError(
                "cannot compare generic inheritance references with mismatched "
                "positional specialization arguments or arities"
            )
        raise OperatorTypeError(
            f"cannot compare incompatible reference operands ('{type_label(left)}' and '{type_label(right)}')"
        )

    raise OperatorTypeError(
        f"operator '{operator}' is not defined for aggregate operands '{type_label(left)}' and '{type_label(right)}'"
    )


def hash_domain(
    operand: TypeExpr | None,
    *,
    class_table: Mapping[str, object] = _EMPTY_MAPPING,
    interface_table: Mapping[str, object] = _EMPTY_MAPPING,
    enum_names: Set[str] = frozenset(),
) -> str:
    if operand is None:
        raise OperatorTypeError("cannot resolve operand type for __btrc_hash")
    if is_scalar_string_type(operand):
        return "string"
    if is_floating_type(operand):
        return "floating"
    if is_numeric_type(operand, enum_names):
        return "integral"
    if operand.base == "__fn_ptr":
        raise OperatorTypeError("__btrc_hash does not support function-pointer operands portably")
    if is_reference_type(operand, class_table, interface_table):
        return "reference"
    raise OperatorTypeError(f"__btrc_hash is not defined for aggregate operand '{type_label(operand)}'")


def coalesce_domain(
    left: TypeExpr | None,
    right: TypeExpr | None,
    *,
    left_is_optional_value: bool = False,
    class_table: Mapping[str, object] = _EMPTY_MAPPING,
    interface_table: Mapping[str, object] = _EMPTY_MAPPING,
    enum_names: Set[str] = frozenset(),
) -> str:
    """Validate ``??`` and identify reference or optional-value lowering."""
    if left is None or right is None:
        raise OperatorTypeError("cannot resolve null-coalescing operand types")
    if left_is_optional_value and not is_reference_type(left, class_table, interface_table):
        if is_numeric_type(left, enum_names) and is_numeric_type(right, enum_names):
            return "optional_value"
        raise OperatorTypeError(
            "null-coalescing optional value and fallback are incompatible: "
            f"'{type_label(left)}' and '{type_label(right)}'"
        )
    if is_scalar_string_type(left):
        compatible = is_scalar_string_type(right) or is_c_string_pointer(right) or is_null_type(right)
    else:
        compatible = reference_types_compatible(left, right, class_table, interface_table)
    if compatible:
        return "reference"
    raise OperatorTypeError(
        "left operand of '??' must be a reference or optional-chain value; "
        f"got '{type_label(left)}' and '{type_label(right)}'"
    )


def type_label(type_expr: TypeExpr) -> str:
    label = type_expr.base
    if type_expr.generic_args:
        args = ", ".join(type_label(item) for item in type_expr.generic_args)
        label += f"<{args}>"
    label += "[]" if type_expr.is_array else ""
    label += "*" * type_expr.pointer_depth
    return label
