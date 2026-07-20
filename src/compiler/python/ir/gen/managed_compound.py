"""Structured operator computation for managed compound assignments."""

from __future__ import annotations

from ...ast_nodes import AssignExpr
from ..nodes import IRExpr


def lower_managed_compound_operator(
    gen,
    assignment: AssignExpr,
    left: IRExpr,
    right: IRExpr,
    target_type,
    right_type,
    *,
    fresh_temp,
) -> IRExpr:
    """Return the ownership-producing operator result for one ``op=``."""
    from .errors import CodegenError
    from .operator_context import operator_context
    from .operators import lower_overloaded_values
    from .typed_operators import lower_typed_binary

    operator = assignment.op[:-1]
    result = lower_overloaded_values(
        gen,
        target_type,
        right_type,
        operator,
        left,
        right,
    )
    if result is None:
        result = lower_typed_binary(
            operator,
            left,
            right,
            target_type,
            right_type,
            operator_context(gen, fresh_temp=fresh_temp),
        )
    if result is None:
        raise CodegenError(f"managed compound operator '{assignment.op}' has no structured lowering")
    return result


def managed_compound_keeps_rhs(gen, target_type, operator: str, right_type) -> bool:
    """Whether the overloaded operator requests a call-duration RHS guard."""
    from .operator_ownership import operator_rhs_keep

    return operator_rhs_keep(gen, target_type, operator, right_type)


__all__ = ["lower_managed_compound_operator", "managed_compound_keeps_rhs"]
