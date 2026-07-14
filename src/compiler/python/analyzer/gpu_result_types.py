"""Contextual scalar result types for the WGSL subset."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast_nodes import BinaryExpr, TernaryExpr, TypeExpr

if TYPE_CHECKING:
    from .gpu_exprs import GpuValidationContext


def set_gpu_type(context: GpuValidationContext, expression, base: str) -> None:
    context.analyzer.node_types[id(expression)] = TypeExpr(base=base)


def copy_gpu_type(context: GpuValidationContext, result, operand) -> None:
    operand_type = context.type_of(operand)
    if operand_type is not None:
        set_gpu_type(context, result, operand_type.base)


def set_binary_result_type(context: GpuValidationContext, expression: BinaryExpr) -> None:
    if expression.op in {"==", "!=", "<", ">", "<=", ">=", "&&", "||"}:
        set_gpu_type(context, expression, "bool")
        return
    left_type = context.type_of(expression.left)
    right_type = context.type_of(expression.right)
    if left_type is None or right_type is None:
        return
    if expression.op in {"&", "|", "^"} and left_type.base == right_type.base == "bool":
        set_gpu_type(context, expression, "bool")
    elif "float" in {left_type.base, right_type.base}:
        set_gpu_type(context, expression, "float")
    else:
        set_gpu_type(context, expression, "int")


def set_ternary_result_type(context: GpuValidationContext, expression: TernaryExpr) -> None:
    true_type = context.type_of(expression.true_expr)
    false_type = context.type_of(expression.false_expr)
    if true_type is None or false_type is None:
        return
    if true_type.base == false_type.base:
        set_gpu_type(context, expression, true_type.base)
    elif {true_type.base, false_type.base} == {"int", "float"}:
        set_gpu_type(context, expression, "float")


__all__ = [
    "copy_gpu_type",
    "set_binary_result_type",
    "set_gpu_type",
    "set_ternary_result_type",
]
