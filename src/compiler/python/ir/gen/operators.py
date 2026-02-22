"""Operator lowering: binary and unary expressions → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import BinaryExpr, UnaryExpr
from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRDeref,
    IRExpr,
    IRLiteral,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .types import is_numeric_type, is_string_type, mangle_generic_type, type_to_c

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
    # Only when BOTH sides are strings (string + int is pointer arithmetic)
    if op == "+" and is_string_type(left_type) and is_string_type(right_type):
        gen.use_helper("__btrc_strcat")
        gen.use_helper("__btrc_str_track")
        cat = IRCall(callee="__btrc_strcat", args=[left, right],
                     helper_ref="__btrc_strcat")
        return IRCall(callee="__btrc_str_track", args=[cat],
                      helper_ref="__btrc_str_track")

    # String comparison: a == b → strcmp(a, b) == 0
    if op in ("==", "!=") and is_string_type(left_type) and is_string_type(right_type):
        cmp = IRCall(callee="strcmp", args=[left, right])
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

    # Null coalescing: a ?? b → ({ T __tmp = a; __tmp != NULL ? __tmp : b; })
    # Uses a temp variable to avoid evaluating left twice (e.g., if it's a call)
    if op == "??":
        tmp = gen.fresh_temp("__nc")
        left_type_expr = gen.analyzed.node_types.get(id(node.left))
        c_type = type_to_c(left_type_expr) if left_type_expr else "void*"
        tmp_var = IRVar(name=tmp)
        return IRStmtExpr(
            stmts=[IRVarDecl(c_type=CType(text=c_type), name=tmp, init=left)],
            result=IRTernary(
                condition=IRBinOp(left=tmp_var, op="!=",
                                  right=IRLiteral(text="NULL")),
                true_expr=tmp_var,
                false_expr=right,
            ),
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
                if left_type.generic_args:
                    cls_c_name = mangle_generic_type(left_type.base, left_type.generic_args)
                else:
                    cls_c_name = left_type.base
                return IRCall(callee=f"{cls_c_name}_{magic}",
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
                if operand_type.generic_args:
                    cls_c_name = mangle_generic_type(operand_type.base, operand_type.generic_args)
                else:
                    cls_c_name = operand_type.base
                return IRCall(callee=f"{cls_c_name}___neg__",
                              args=[operand])
    return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)
