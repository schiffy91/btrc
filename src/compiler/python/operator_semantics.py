"""Owned type-domain rules for comparison, coalescing, and generic hashing."""

from __future__ import annotations

from collections.abc import Mapping, Set

from .ast_nodes import TypeExpr
from .numeric_semantics import is_floating_type, is_numeric_type
from .type_identity import TypeIdentity

COMPARISON_OPERATORS = frozenset(("==", "!=", "<", ">", "<=", ">="))
EQUALITY_OPERATORS = frozenset(("==", "!="))
GENERIC_COMPARISON_INTRINSICS = {
    "__btrc_eq": "==",
    "__btrc_lt": "<",
    "__btrc_gt": ">",
}
GENERIC_INTRINSICS = frozenset((*GENERIC_COMPARISON_INTRINSICS, "__btrc_hash"))


class OperatorTypeError(ValueError):
    """A typed operator has no portable meaning for its concrete operands."""


class OperatorSemantics:
    """Own portable operator domains for one compiler composition."""

    def __init__(
        self,
        type_identity: TypeIdentity,
        *,
        class_table: Mapping[str, object] | None = None,
        interface_table: Mapping[str, object] | None = None,
        enum_names: Set[str] | Mapping[str, object] | None = None,
    ) -> None:
        self.type_identity = type_identity
        self.class_table = class_table if class_table is not None else {}
        self.interface_table = interface_table if interface_table is not None else {}
        self.enum_names = enum_names if enum_names is not None else frozenset()

    def comparison_domain(
        self,
        operator: str,
        left: TypeExpr | None,
        right: TypeExpr | None,
    ) -> str:
        """Return ``string``, ``numeric``, or ``reference`` after validation."""
        if operator not in COMPARISON_OPERATORS:
            raise OperatorTypeError(f"unsupported comparison operator '{operator}'")
        if left is None or right is None:
            raise OperatorTypeError(f"cannot resolve operand types for operator '{operator}'")

        identity = self.type_identity
        left_string = identity.is_scalar_string(left)
        right_string = identity.is_scalar_string(right)
        if left_string or right_string:
            if (left_string or identity.is_c_string_pointer(left) or identity.is_null(left)) and (
                right_string or identity.is_c_string_pointer(right) or identity.is_null(right)
            ):
                return "string"
            raise OperatorTypeError(
                "cannot compare string and non-string operands "
                f"('{self.type_label(left)}' and '{self.type_label(right)}')"
            )

        if is_numeric_type(left, self.enum_names) and is_numeric_type(right, self.enum_names):
            return "numeric"

        left_reference = identity.is_reference(left, self.class_table, self.interface_table)
        right_reference = identity.is_reference(right, self.class_table, self.interface_table)
        if left_reference or right_reference:
            if operator not in EQUALITY_OPERATORS:
                raise OperatorTypeError(
                    f"operator '{operator}' is not defined for reference operands; only == and != are portable"
                )
            if identity.references_compatible(
                left,
                right,
                self.class_table,
                self.interface_table,
            ):
                return "reference"
            if (left.generic_args or right.generic_args) and identity.nominally_related(
                left.base,
                right.base,
                self.class_table,
                self.interface_table,
            ):
                raise OperatorTypeError(
                    "cannot compare generic inheritance references with mismatched "
                    "positional specialization arguments or arities"
                )
            raise OperatorTypeError(
                "cannot compare incompatible reference operands "
                f"('{self.type_label(left)}' and '{self.type_label(right)}')"
            )

        raise OperatorTypeError(
            f"operator '{operator}' is not defined for aggregate operands "
            f"'{self.type_label(left)}' and '{self.type_label(right)}'"
        )

    def hash_domain(self, operand: TypeExpr | None) -> str:
        """Return the runtime hashing domain for one concrete operand."""
        if operand is None:
            raise OperatorTypeError("cannot resolve operand type for __btrc_hash")
        if self.type_identity.is_scalar_string(operand):
            return "string"
        if is_floating_type(operand):
            return "floating"
        if is_numeric_type(operand, self.enum_names):
            return "integral"
        if operand.base == "__fn_ptr":
            raise OperatorTypeError("__btrc_hash does not support function-pointer operands portably")
        if self.type_identity.is_reference(
            operand,
            self.class_table,
            self.interface_table,
        ):
            return "reference"
        raise OperatorTypeError(f"__btrc_hash is not defined for aggregate operand '{self.type_label(operand)}'")

    def coalesce_domain(
        self,
        left: TypeExpr | None,
        right: TypeExpr | None,
        *,
        left_is_optional_value: bool = False,
    ) -> str:
        """Validate ``??`` and identify reference or optional-value lowering."""
        if left is None or right is None:
            raise OperatorTypeError("cannot resolve null-coalescing operand types")
        identity = self.type_identity
        if left_is_optional_value and not identity.is_reference(
            left,
            self.class_table,
            self.interface_table,
        ):
            if is_numeric_type(left, self.enum_names) and is_numeric_type(right, self.enum_names):
                return "optional_value"
            raise OperatorTypeError(
                "null-coalescing optional value and fallback are incompatible: "
                f"'{self.type_label(left)}' and '{self.type_label(right)}'"
            )
        if identity.is_scalar_string(left):
            compatible = (
                identity.is_scalar_string(right) or identity.is_c_string_pointer(right) or identity.is_null(right)
            )
        else:
            compatible = identity.references_compatible(
                left,
                right,
                self.class_table,
                self.interface_table,
            )
        if compatible:
            return "reference"
        raise OperatorTypeError(
            "left operand of '??' must be a reference or optional-chain value; "
            f"got '{self.type_label(left)}' and '{self.type_label(right)}'"
        )

    def type_label(self, type_expr: TypeExpr) -> str:
        """Format a recursive source type for operator diagnostics."""
        label = type_expr.base
        if type_expr.generic_args:
            arguments = ", ".join(self.type_label(item) for item in type_expr.generic_args)
            label += f"<{arguments}>"
        label += "[]" if type_expr.is_array else ""
        label += "*" * type_expr.pointer_depth
        return label


__all__ = [
    "COMPARISON_OPERATORS",
    "EQUALITY_OPERATORS",
    "GENERIC_COMPARISON_INTRINSICS",
    "GENERIC_INTRINSICS",
    "OperatorSemantics",
    "OperatorTypeError",
]
