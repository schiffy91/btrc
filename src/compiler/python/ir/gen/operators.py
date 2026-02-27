"""Operator lowering: binary and unary expressions → IR."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import BinaryExpr, UnaryExpr
from ..nodes import (
    IRAddressOf, IRBinOp, IRCall, IRDeref, IRExpr,
    IRLiteral, IRTernary, IRUnaryOp,
)
from .types import is_string_type, is_numeric_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_binary(gen: IRGenerator, node: BinaryExpr) -> IRExpr:
    """Lower a binary expression, handling special operators."""
    from .expressions import lower_expr

    left = lower_expr(gen, node.left)
    right = lower_expr(gen, node.right)

    # Infer types for special handling
    left_type = gen.analyzed.node_types.get(id(node.left))
    right_type = gen.analyzed.node_types.get(id(node.right))

    op = node.op

    # String concatenation: a + b → __btrc_str_track(__btrc_strcat(a, b))
    if op == "+" and is_string_type(left_type):
        gen.use_helper("__btrc_strcat")
        gen.use_helper("__btrc_str_track")
        cat = IRCall(callee="__btrc_strcat", args=[left, right],
                     helper_ref="__btrc_strcat")
        return IRCall(callee="__btrc_str_track", args=[cat],
                      helper_ref="__btrc_str_track")

    # String comparison: a == b → strcmp(a, b) == 0
    if op in ("==", "!=") and is_string_type(left_type):
        cmp = IRCall(callee="strcmp", args=[left, right])
        cmp_val = "0" if op == "==" else "0"
        cmp_op = "==" if op == "==" else "!="
        return IRBinOp(left=cmp, op=cmp_op, right=IRLiteral(text="0"))

    # Division: a / b → __btrc_div_int(a, b)
    if op == "/" and is_numeric_type(left_type):
        if left_type and left_type.base in ("float", "double"):
            gen.use_helper("__btrc_div_double")
            return IRCall(callee="__btrc_div_double", args=[left, right],
                          helper_ref="__btrc_div_double")
        gen.use_helper("__btrc_div_int")
        return IRCall(callee="__btrc_div_int", args=[left, right],
                      helper_ref="__btrc_div_int")

    # Modulo: a % b → __btrc_mod_int(a, b)
    if op == "%" and is_numeric_type(left_type):
        gen.use_helper("__btrc_mod_int")
        return IRCall(callee="__btrc_mod_int", args=[left, right],
                      helper_ref="__btrc_mod_int")

    # Null coalescing: a ?? b → (a != NULL ? a : b)
    if op == "??":
        return IRTernary(
            condition=IRBinOp(left=left, op="!=", right=IRLiteral(text="NULL")),
            true_expr=left,
            false_expr=right,
        )

    # Operator overloading on class types: a + b → ClassName___add__(a, b)
    if left_type and left_type.base in gen.analyzed.class_table:
        op_map = {
            "+": "__add__", "-": "__sub__", "*": "__mul__",
            "/": "__div__", "%": "__mod__",
            "==": "__eq__", "!=": "__ne__",
            "<": "__lt__", ">": "__gt__",
            "<=": "__le__", ">=": "__ge__",
        }
        if op in op_map:
            cls_info = gen.analyzed.class_table[left_type.base]
            magic = op_map[op]
            if magic in cls_info.methods:
                return IRCall(callee=f"{left_type.base}_{magic}",
                              args=[left, right])

    return IRBinOp(left=left, op=op, right=right)


def _lower_unary(gen: IRGenerator, node: UnaryExpr) -> IRExpr:
    from .expressions import lower_expr

    operand = lower_expr(gen, node.operand)
    op = node.op
    if op == "&":
        return IRAddressOf(expr=operand)
    if op == "*":
        return IRDeref(expr=operand)
    # Operator overloading: -obj where obj is class with __neg__
    if op == "-" and node.prefix:
        operand_type = gen.analyzed.node_types.get(id(node.operand))
        if operand_type and operand_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[operand_type.base]
            if "__neg__" in cls_info.methods:
                return IRCall(callee=f"{operand_type.base}___neg__",
                              args=[operand])
    return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)
