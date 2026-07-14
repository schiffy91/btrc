"""Portable type-directed hashing for generic and ordinary call paths."""

from ...ast_nodes import TypeExpr
from ...operator_semantics import OperatorTypeError, hash_domain
from ..nodes import CType, IRCall, IRCast, IRExpr
from .errors import TypedOperatorError
from .operator_context import (
    OperatorLoweringContext,
    canonical_operator_type,
)


def lower_typed_hash(
    operand: IRExpr,
    operand_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    operand_type = canonical_operator_type(context, operand_type)
    try:
        domain = hash_domain(
            operand_type,
            class_table=context.class_table,
            interface_table=context.interface_table,
            enum_names=context.enum_names,
        )
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
