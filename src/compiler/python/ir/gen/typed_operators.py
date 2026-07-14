"""Portable type-directed lowering shared by every Python IR expression path."""

from __future__ import annotations

from ...ast_nodes import TypeExpr
from ...operator_semantics import (
    OperatorTypeError,
    coalesce_domain,
    comparison_domain,
    is_null_type,
    is_numeric_type,
    is_scalar_string_type,
    type_label,
)
from ...reference_semantics import is_c_string_pointer
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRExpr,
    IRLiteral,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .errors import TypedOperatorError
from .operator_context import (
    OperatorLoweringContext,
    canonical_operator_type,
    operator_context,
)
from .optional_fallback import replace_optional_fallback
from .typed_hash import lower_typed_hash
from .typed_numeric import (
    lower_checked_divmod,
    lower_numeric_comparison,
    lower_numeric_operation,
    lower_typed_ternary,
)
from .types import type_to_c


def lower_typed_binary(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
    context: OperatorLoweringContext,
    *,
    allow_unresolved_c_operands: bool = False,
    left_is_optional_value: bool = False,
) -> IRExpr | None:
    """Lower an operation owned by the shared portable type contract."""
    left_type = canonical_operator_type(context, left_type)
    right_type = canonical_operator_type(context, right_type)
    if allow_unresolved_c_operands and (left_type is None or right_type is None):
        return IRBinOp(left=left, op=operator, right=right)
    if (
        operator == "+"
        and (is_scalar_string_type(left_type) or is_c_string_pointer(left_type))
        and (is_scalar_string_type(right_type) or is_c_string_pointer(right_type))
        and (is_scalar_string_type(left_type) or is_scalar_string_type(right_type))
    ):
        _use(context, "__btrc_strcat")
        _use(context, "__btrc_str_track")
        joined = IRCall(
            callee="__btrc_strcat",
            args=[left, right],
            helper_ref="__btrc_strcat",
        )
        return IRCall(
            callee="__btrc_str_track",
            args=[joined],
            helper_ref="__btrc_str_track",
        )

    if operator in {"==", "!=", "<", ">", "<=", ">="}:
        return lower_typed_comparison(operator, left, right, left_type, right_type, context)

    if (
        operator in {"+", "-", "*", "&", "|", "^"}
        and is_numeric_type(left_type, context.enum_names)
        and is_numeric_type(right_type, context.enum_names)
    ):
        return lower_numeric_operation(operator, left, right, left_type, right_type, context)

    if operator in {"/", "%"}:
        return lower_checked_divmod(operator, left, right, left_type, right_type, context)

    if operator == "??":
        return _lower_null_coalesce(
            left, right, left_type, right_type, context, left_is_optional_value=left_is_optional_value
        )

    return None


def lower_typed_comparison(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
    context: OperatorLoweringContext,
) -> IRExpr:
    left_type = canonical_operator_type(context, left_type)
    right_type = canonical_operator_type(context, right_type)
    try:
        domain = comparison_domain(
            operator,
            left_type,
            right_type,
            class_table=context.class_table,
            interface_table=context.interface_table,
            enum_names=context.enum_names,
        )
    except OperatorTypeError as error:
        raise TypedOperatorError(str(error)) from error

    if domain == "string":
        return _lower_string_comparison(operator, left, right, context)
    if domain == "reference":
        return _lower_reference_equality(operator, left, right, left_type, right_type)
    return lower_numeric_comparison(operator, left, right, left_type, right_type, context)


def _lower_string_comparison(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    context: OperatorLoweringContext,
) -> IRExpr:
    left_name = context.fresh_temp("__btrc_cmp_left")
    right_name = context.fresh_temp("__btrc_cmp_right")
    left_var = IRVar(name=left_name)
    right_var = IRVar(name=right_name)
    zero = IRLiteral(text="0")
    null = IRLiteral(text="NULL")
    compare_value = IRTernary(
        condition=IRBinOp(left=left_var, op="==", right=right_var),
        true_expr=zero,
        false_expr=IRTernary(
            condition=IRBinOp(left=left_var, op="==", right=null),
            true_expr=IRLiteral(text="-1"),
            false_expr=IRTernary(
                condition=IRBinOp(left=right_var, op="==", right=null),
                true_expr=IRLiteral(text="1"),
                false_expr=IRCall(callee="strcmp", args=[left_var, right_var]),
            ),
        ),
    )
    return IRStmtExpr(
        stmts=[
            IRVarDecl(c_type=CType(text="const char*"), name=left_name),
            IRVarDecl(c_type=CType(text="const char*"), name=right_name),
        ],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=left_var, op="=", right=left),
                IRBinOp(left=right_var, op="=", right=right),
                IRBinOp(left=compare_value, op=operator, right=zero),
            ]
        ),
    )


def _lower_reference_equality(
    operator: str,
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
) -> IRExpr:
    if is_null_type(left_type) or is_null_type(right_type):
        function_type = next(
            (item for item in (left_type, right_type) if item is not None and item.base == "__fn_ptr"),
            None,
        )
        if function_type is not None:
            null_value = IRCast(
                target_type=CType(text=type_to_c(function_type)),
                expr=IRLiteral(text="0"),
            )
            if is_null_type(left_type):
                left = null_value
            else:
                right = null_value
        return IRBinOp(left=left, op=operator, right=right)
    if left_type and right_type and left_type.base == right_type.base == "__fn_ptr":
        return IRBinOp(left=left, op=operator, right=right)
    void_ptr = CType(text="const void*")
    return IRBinOp(
        left=IRCast(target_type=void_ptr, expr=left),
        op=operator,
        right=IRCast(target_type=void_ptr, expr=right),
    )


def _lower_null_coalesce(
    left: IRExpr,
    right: IRExpr,
    left_type: TypeExpr | None,
    right_type: TypeExpr | None,
    context: OperatorLoweringContext,
    *,
    left_is_optional_value: bool,
) -> IRExpr:
    try:
        domain = coalesce_domain(
            left_type,
            right_type,
            left_is_optional_value=left_is_optional_value,
            class_table=context.class_table,
            interface_table=context.interface_table,
            enum_names=context.enum_names,
        )
    except OperatorTypeError as error:
        raise TypedOperatorError(str(error)) from error
    if domain == "optional_value":
        optional = replace_optional_fallback(left, right)
        if optional is None:
            raise TypedOperatorError("optional-chain coalescing requires structured ternary IR")
        return optional
    result_type = right_type if is_null_type(left_type) else left_type
    if result_type is None:
        raise TypedOperatorError("cannot resolve null-coalescing result type")
    temp_name = context.fresh_temp("__nc")
    temp = IRVar(name=temp_name)
    return IRStmtExpr(
        stmts=[IRVarDecl(c_type=CType(text=type_to_c(result_type)), name=temp_name)],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=temp, op="=", right=left),
                IRTernary(
                    condition=IRBinOp(left=temp, op="!=", right=IRLiteral(text="NULL")),
                    true_expr=temp,
                    false_expr=right,
                ),
            ]
        ),
    )


def _use(context: OperatorLoweringContext, helper: str) -> None:
    if context.use_helper is not None:
        context.use_helper(helper)


def _label(type_expr: TypeExpr | None) -> str:
    return type_label(type_expr) if type_expr is not None else "unknown"


__all__ = [
    "OperatorLoweringContext",
    "lower_typed_binary",
    "lower_typed_comparison",
    "lower_typed_hash",
    "lower_typed_ternary",
    "operator_context",
]
