"""Operator lowering: binary and unary expressions → IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import BinaryExpr, FieldAccessExpr, IndexExpr, UnaryExpr
from ..nodes import (
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRDeref,
    IRExpr,
    IRUnaryOp,
)
from .managed_values import is_managed_type
from .typed_operators import lower_typed_binary, operator_context
from .types import mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_binary(gen: IRGenerator, node: BinaryExpr) -> IRExpr:
    """Lower a binary expression, handling special operators."""
    if node.op == "+":
        from .string_concat import lower_long_string_concat

        flattened = lower_long_string_concat(gen, node)
        if flattened is not None:
            return flattened
    if node.op not in {"??", "&&", "||"}:
        from .evaluation_order import has_observable_effect
        from .operator_ownership import operator_rhs_keep
        from .ownership_boundary import sequence_owned_operands

        left_type = gen.analyzed.node_types.get(id(node.left))
        right_type = gen.analyzed.node_types.get(id(node.right))
        keep_nodes = [node.right] if operator_rhs_keep(gen, left_type, node.op, right_type) else []
        pin_nodes = (
            [node.left]
            if overloaded_binary_method(gen, left_type, node.op) is not None and is_managed_type(gen, left_type)
            else []
        )

        sequenced = sequence_owned_operands(
            gen,
            [node.left, node.right],
            build=lambda: _lower_binary_plain(gen, node),
            result_type=gen.analyzed.node_types.get(id(node)),
            keep_nodes=keep_nodes,
            pin_nodes=pin_nodes,
            force=(has_observable_effect(gen, node.left) or has_observable_effect(gen, node.right)),
        )
        if sequenced is not None:
            return sequenced
    return _lower_binary_plain(gen, node)


def _lower_binary_plain(gen: IRGenerator, node: BinaryExpr) -> IRExpr:
    """Lower one binary operation after owned operands are stabilized."""
    from .expressions import lower_expr

    left = lower_expr(gen, node.left)
    right = lower_expr(gen, node.right)

    if node.op == "??":
        from .ownership import normalize_owned_branch, owns_result

        if owns_result(gen, node):
            left = normalize_owned_branch(gen, node.left, left)
            right = normalize_owned_branch(gen, node.right, right)

    # Infer types for special handling
    left_type = gen.analyzed.node_types.get(id(node.left))
    right_type = gen.analyzed.node_types.get(id(node.right))

    op = node.op

    overloaded = lower_overloaded_values(gen, left_type, right_type, op, left, right)
    if overloaded is not None:
        return overloaded

    lowered = lower_typed_binary(
        op,
        left,
        right,
        left_type,
        right_type,
        operator_context(gen),
        allow_unresolved_c_operands=True,
        left_is_optional_value=(isinstance(node.left, FieldAccessExpr) and node.left.optional),
    )
    if lowered is not None:
        return lowered

    return IRBinOp(left=left, op=op, right=right)


def lower_overloaded_binary(
    gen: IRGenerator, left_node, right_node, op: str, left: IRExpr, right: IRExpr
) -> IRExpr | None:
    """Lower one class binary operation, or return ``None`` if not overloaded."""

    left_type = gen.analyzed.node_types.get(id(left_node))
    right_type = gen.analyzed.node_types.get(id(right_node))
    return lower_overloaded_values(gen, left_type, right_type, op, left, right)


def lower_overloaded_values(
    gen: IRGenerator, left_type, right_type, op: str, left: IRExpr, right: IRExpr
) -> IRExpr | None:
    """Lower one class operation from already-resolved operand types."""

    method = overloaded_binary_method(gen, left_type, op)
    if method is None:
        return None

    if method.params:
        from .upcast import upcast_class_pointer

        right = upcast_class_pointer(gen, method.params[0].type, right_type, right)
    class_name = (
        mangle_generic_type(left_type.base, left_type.generic_args) if left_type.generic_args else left_type.base
    )
    return IRCall(callee=f"{class_name}_{_operator_method_name(op)}", args=[left, right])


def overloaded_binary_method(gen: IRGenerator, left_type, op: str):
    """Return the source method implementing an overloaded binary operator."""
    magic = _operator_method_name(op)
    if not magic or not left_type:
        return None
    cls_info = gen.analyzed.class_table.get(left_type.base)
    if cls_info is None:
        return None
    return cls_info.methods.get(magic)


def _operator_method_name(op: str) -> str | None:
    return {
        "+": "__add__",
        "-": "__sub__",
        "*": "__mul__",
        "/": "__div__",
        "%": "__mod__",
        "==": "__eq__",
        "!=": "__ne__",
        "<": "__lt__",
        ">": "__gt__",
        "<=": "__le__",
        ">=": "__ge__",
    }.get(op)


def _lower_unary(gen: IRGenerator, node: UnaryExpr) -> IRExpr:
    if node.op in {"++", "--"} and isinstance(
        node.operand,
        (FieldAccessExpr, IndexExpr),
    ):
        from .ownership_boundary import sequence_owned_operands

        target_nodes = [node.operand.obj]
        if isinstance(node.operand, IndexExpr):
            target_nodes.append(node.operand.index)
        result_type = gen.analyzed.node_types.get(id(node))
        sequenced = sequence_owned_operands(
            gen,
            target_nodes,
            build=lambda: _lower_unary_plain(gen, node),
            result_type=result_type,
            promote_result=bool(is_managed_type(gen, result_type)),
        )
        if sequenced is not None:
            return sequenced
    if node.op not in {"++", "--", "&", "*"}:
        from .ownership_boundary import sequence_owned_operands

        sequenced = sequence_owned_operands(
            gen,
            [node.operand],
            build=lambda: _lower_unary_plain(gen, node),
            result_type=gen.analyzed.node_types.get(id(node)),
        )
        if sequenced is not None:
            return sequenced
    return _lower_unary_plain(gen, node)


def _lower_unary_plain(gen: IRGenerator, node: UnaryExpr) -> IRExpr:
    from .expressions import lower_expr

    op = node.op
    if op in {"++", "--"}:
        from .updates import generator_update_context, lower_incdec

        return lower_incdec(generator_update_context(gen), node)

    operand = lower_expr(gen, node.operand)
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
                return IRCall(callee=f"{cls_c_name}___neg__", args=[operand])
    return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)
