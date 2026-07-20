"""Canonical numeric arithmetic, divmod, comparison, and ternary lowering."""

from ...ast_nodes import TypeExpr
from ...numeric_semantics import (
    is_numeric_type,
    numeric_operands_need_cast,
    numeric_result_type,
)
from ..nodes import CType, IRBinOp, IRCall, IRCast, IRExpr, IRTernary
from .errors import TypedOperatorError
from .operator_context import (
    OperatorLoweringContext,
    canonical_operator_type,
)
from .types import type_to_c


def lower_numeric_operation(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    result_type = numeric_result_type(left_type, right_type, context.enum_names)
    if result_type is None:
        raise TypedOperatorError(f"cannot resolve numeric result type for operator '{operator}'")
    target = CType(text=type_to_c(result_type))
    if (
        left_type is not None
        and right_type is not None
        and not numeric_operands_need_cast(left_type, right_type, context.enum_names)
    ):
        return IRBinOp(left=left, op=operator, right=right)
    return IRBinOp(
        left=IRCast(target_type=target, expr=left),
        op=operator,
        right=IRCast(target_type=target, expr=right),
    )


def lower_numeric_comparison(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    """Compare mixed numeric types in their explicit language-level domain."""
    result_type = numeric_result_type(left_type, right_type, context.enum_names)
    if result_type is None:
        raise TypedOperatorError(f"cannot resolve numeric result type for operator '{operator}'")
    if left_type is not None and right_type is not None and left_type.base == right_type.base:
        return IRBinOp(left=left, op=operator, right=right)
    target = CType(text=type_to_c(result_type))
    return IRBinOp(
        left=IRCast(target_type=target, expr=left),
        op=operator,
        right=IRCast(target_type=target, expr=right),
    )


def lower_checked_divmod(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    if not (is_numeric_type(left_type, context.enum_names) and is_numeric_type(right_type, context.enum_names)):
        raise TypedOperatorError(f"operator '{operator}' requires numeric operands")
    result_type = numeric_result_type(left_type, right_type, context.enum_names)
    if result_type is None:
        raise TypedOperatorError("cannot resolve divmod result type")
    target = CType(text=type_to_c(result_type))
    helper = "__btrc_mod" if operator == "%" else "__btrc_div"
    if context.use_helper is not None:
        context.use_helper(helper)
    call = IRCall(
        callee=helper,
        args=[
            IRCast(target_type=target, expr=left),
            IRCast(target_type=target, expr=right),
        ],
        helper_ref=helper,
    )
    return IRCast(target_type=target, expr=call)


def lower_typed_ternary(
    condition: IRExpr,
    true_expr: IRExpr,
    false_expr: IRExpr,
    true_type: TypeExpr | None,
    false_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    true_type = canonical_operator_type(context, true_type)
    false_type = canonical_operator_type(context, false_type)
    result_type = numeric_result_type(true_type, false_type, context.enum_names)
    if (
        result_type is not None
        and true_type is not None
        and false_type is not None
        and numeric_operands_need_cast(true_type, false_type, context.enum_names)
    ):
        target = CType(text=type_to_c(result_type))
        true_expr = IRCast(target_type=target, expr=true_expr)
        false_expr = IRCast(target_type=target, expr=false_expr)
    return IRTernary(
        condition=condition,
        true_expr=true_expr,
        false_expr=false_expr,
    )
