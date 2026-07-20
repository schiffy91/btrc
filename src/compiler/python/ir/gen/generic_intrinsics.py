"""Type-directed lowering for generic comparison and hashing intrinsics."""

from __future__ import annotations

from collections.abc import Sequence

from ...ast_nodes import TypeExpr
from ...operator_semantics import (
    GENERIC_COMPARISON_INTRINSICS,
    GENERIC_INTRINSICS,
)
from ..nodes import IRExpr
from .errors import CodegenError
from .operator_context import OperatorLoweringContext
from .typed_operators import (
    lower_typed_comparison,
    lower_typed_hash,
)


def lower_generic_intrinsic(
    name: str,
    args: Sequence[IRExpr],
    operand_types: Sequence[TypeExpr | None],
    context: OperatorLoweringContext,
) -> IRExpr | None:
    """Lower a generic intrinsic to portable structured IR when name matches."""
    if name not in GENERIC_INTRINSICS:
        return None

    expected_arity = 1 if name == "__btrc_hash" else 2
    if len(args) != expected_arity:
        raise CodegenError(f"{name} expects {expected_arity} operand(s), got {len(args)}")
    if len(operand_types) != expected_arity:
        raise CodegenError(f"cannot resolve all operand types for {name}")
    if name in GENERIC_COMPARISON_INTRINSICS:
        return lower_typed_comparison(
            GENERIC_COMPARISON_INTRINSICS[name],
            args[0],
            args[1],
            operand_types[0],
            operand_types[1],
            context,
        )
    return lower_typed_hash(args[0], operand_types[0], context)


__all__ = ["GENERIC_INTRINSICS", "lower_generic_intrinsic"]
