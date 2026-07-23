"""Portable type-directed hashing for generic and ordinary call paths."""

from ...ast_nodes import TypeExpr
from ...operator_semantics import OperatorTypeError
from ..nodes import CType, IRCall, IRCast, IRExpr
from .errors import TypedOperatorError
from .operator_context import (
    OperatorLoweringContext,
)


def lower_typed_hash(
    operand: IRExpr,
    operand_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    operand_type = context.canonical_type(operand_type)
    try:
        domain = context.operator_types.hash_domain(operand_type)
    except OperatorTypeError as error:
        raise TypedOperatorError(str(error)) from error

    if domain == "string":
        _use(context, "__btrc_hash_str")
        return IRCall(
            callee="__btrc_hash_str",
            args=[operand],
            helper_ref="__btrc_hash_str",
        )
    if domain == "integral":
        return IRCast(target_type=CType(text="unsigned int"), expr=operand)
    if domain == "floating":
        _use(context, "__btrc_hash_real")
        return IRCall(
            callee="__btrc_hash_real",
            args=[operand],
            helper_ref="__btrc_hash_real",
        )
    return IRCast(
        target_type=CType(text="unsigned int"),
        expr=IRCast(target_type=CType(text="uintptr_t"), expr=operand),
    )


def _use(context: OperatorLoweringContext, helper: str) -> None:
    if context.use_helper is not None:
        context.use_helper(helper)
