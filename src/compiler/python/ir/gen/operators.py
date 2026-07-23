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
from .operator_context import OperatorLoweringContext
from .typed_operators import lower_typed_binary
from .types import CTypeRenderer

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def _lower_binary(
    gen: IRLowerer,
    node: BinaryExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower a binary expression, handling special operators."""
    if node.op == "+":
        from .string_concat import lower_long_string_concat

        flattened = lower_long_string_concat(
            gen,
            node,
            type_renderer,
            default_arguments,
        )
        if flattened is not None:
            return flattened
    prepared_overload = _lower_prepared_overload(
        gen,
        node,
        type_renderer,
        default_arguments,
    )
    if prepared_overload is not None:
        return prepared_overload
    if node.op not in {"??", "&&", "||"}:
        from .evaluation_order import operands_require_order
        from .operator_ownership import operator_rhs_keep

        left_type = gen.analyzed.node_types.get(id(node.left))
        right_type = gen.analyzed.node_types.get(id(node.right))
        keep_nodes = [node.right] if operator_rhs_keep(gen, left_type, node.op, right_type) else []
        pin_nodes = (
            [node.left]
            if overloaded_binary_method(gen, left_type, node.op) is not None and is_managed_type(gen, left_type)
            else []
        )

        sequenced = gen.ownership.sequence_operands(
            [node.left, node.right],
            build=lambda: _lower_binary_plain(
                gen,
                node,
                type_renderer,
                default_arguments,
            ),
            result_type=gen.analyzed.node_types.get(id(node)),
            keep_nodes=keep_nodes,
            pin_nodes=pin_nodes,
            force=operands_require_order(gen, [node.left, node.right]),
            allow_trailing_opaque=True,
            opaque_context=f"operator '{node.op}'",
        )
        if sequenced is not None:
            return sequenced
    return _lower_binary_plain(
        gen,
        node,
        type_renderer,
        default_arguments,
    )


def _lower_binary_plain(
    gen: IRLowerer,
    node: BinaryExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower one binary operation after owned operands are stabilized."""
    from .expressions import lower_expr

    left = lower_expr(
        gen,
        node.left,
        type_renderer,
        default_arguments,
    )
    right = lower_expr(
        gen,
        node.right,
        type_renderer,
        default_arguments,
    )

    if node.op == "??":
        if gen.ownership.owns_result(node):
            left = gen.ownership.normalize_branch(node.left, left)
            right = gen.ownership.normalize_branch(node.right, right)

    # Infer types for special handling
    left_type = gen.analyzed.node_types.get(id(node.left))
    right_type = gen.analyzed.node_types.get(id(node.right))

    op = node.op

    overloaded = lower_overloaded_values(
        gen,
        left_type,
        right_type,
        op,
        left,
        right,
        type_renderer,
    )
    if overloaded is not None:
        return overloaded

    lowered = lower_typed_binary(
        op,
        left,
        right,
        left_type,
        right_type,
        OperatorLoweringContext.from_lowerer(gen, type_renderer),
        allow_unresolved_c_operands=True,
        left_is_optional_value=(isinstance(node.left, FieldAccessExpr) and node.left.optional),
    )
    if lowered is not None:
        return lowered

    return IRBinOp(left=left, op=op, right=right)


def lower_overloaded_binary(
    gen: IRLowerer,
    left_node,
    right_node,
    op: str,
    left: IRExpr,
    right: IRExpr,
    type_renderer: CTypeRenderer,
) -> IRExpr | None:
    """Lower one class binary operation, or return ``None`` if not overloaded."""

    left_type = gen.analyzed.node_types.get(id(left_node))
    right_type = gen.analyzed.node_types.get(id(right_node))
    return lower_overloaded_values(
        gen,
        left_type,
        right_type,
        op,
        left,
        right,
        type_renderer,
    )


def lower_overloaded_values(
    gen: IRLowerer,
    left_type,
    right_type,
    op: str,
    left: IRExpr,
    right: IRExpr,
    type_renderer: CTypeRenderer,
) -> IRExpr | None:
    """Lower one class operation from already-resolved operand types."""

    method = overloaded_binary_method(gen, left_type, op)
    if method is None:
        return None

    if method.params:
        from .upcast import upcast_class_pointer

        # Overload dispatch is called only from owners that already rendered
        # the prepared operand; ordinary source-class upcasts are handled at
        # argument binding boundaries.
        right = upcast_class_pointer(
            gen,
            method.params[0].type,
            right_type,
            right,
            type_renderer,
        )
    class_name = (
        gen.type_identity.specialization_symbol(left_type.base, left_type.generic_args)
        if left_type.generic_args
        else left_type.base
    )
    return IRCall(callee=f"{class_name}_{_operator_method_name(op)}", args=[left, right])


def overloaded_binary_method(gen: IRLowerer, left_type, op: str):
    """Return the source method implementing an overloaded binary operator."""
    magic = _operator_method_name(op)
    if not magic or not left_type:
        return None
    cls_info = gen.analyzed.class_table.get(left_type.base)
    if cls_info is None:
        return None
    return cls_info.methods.get(magic)


def resolved_operator_param_type(gen, left_type, method):
    """Resolve an overload RHS type against its concrete receiver."""
    if method is None or not method.params:
        return None
    expected = method.params[0].type
    cls = gen.analyzed.class_table.get(left_type.base) if left_type else None
    if cls and cls.generic_params and left_type.generic_args:
        from .type_resolution import substitute_concrete_type

        expected = substitute_concrete_type(
            expected,
            dict(zip(cls.generic_params, left_type.generic_args)),
            gen.analyzed.typedef_table,
            gen.type_identity,
        )
    return expected


def _lower_prepared_overload(
    gen,
    node,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Lower an overload whose RHS needs target-directed conversion."""
    left_type = gen.analyzed.node_types.get(id(node.left))
    right_type = gen.analyzed.node_types.get(id(node.right))
    method = overloaded_binary_method(gen, left_type, node.op)
    expected = resolved_operator_param_type(gen, left_type, method)
    if expected is None:
        return None
    from .prepared_values import prepare_normal_value, requires_string_conversion

    if not requires_string_conversion(gen, expected, right_type):
        return None
    left = prepare_normal_value(
        gen,
        node.left,
        left_type,
        type_renderer,
        default_arguments=default_arguments,
    )
    right = prepare_normal_value(
        gen,
        node.right,
        expected,
        type_renderer,
        default_arguments=default_arguments,
    )
    from .call_boundary import CallOperand
    from .evaluation_order import borrowed_value_can_be_pinned

    operands = [
        CallOperand(
            node=node.left,
            type_expr=left.effective_type,
            c_type=type_renderer.render(left.effective_type),
            pin=bool(
                borrowed_value_can_be_pinned(node.left) and is_managed_type(gen, left.effective_type) and not left.owned
            ),
            owned=left.owned,
            lowered=left.value,
        ),
        CallOperand(
            node=node.right,
            type_expr=right.effective_type,
            c_type=type_renderer.render(right.effective_type),
            keep=bool(method.params[0].keep),
            owned=right.owned,
            lowered=right.value,
        ),
    ]

    return gen.ownership.boundaries.sequence(
        operands,
        lower_expr=lambda _node: None,
        build_call=lambda values: lower_overloaded_values(
            gen,
            left.effective_type,
            right.effective_type,
            node.op,
            values[id(node.left)],
            values[id(node.right)],
            type_renderer,
        ),
        result_c_type=type_renderer.render(gen.analyzed.node_types.get(id(node))),
        result_type=gen.analyzed.node_types.get(id(node)),
        result_owned=gen.ownership.owns_result(node),
    )


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


def _lower_unary(
    gen: IRLowerer,
    node: UnaryExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    if node.op in {"++", "--"} and isinstance(
        node.operand,
        (FieldAccessExpr, IndexExpr),
    ):
        target_nodes = [node.operand.obj]
        if isinstance(node.operand, IndexExpr):
            target_nodes.append(node.operand.index)
        result_type = gen.analyzed.node_types.get(id(node))
        sequenced = gen.ownership.sequence_operands(
            target_nodes,
            build=lambda: _lower_unary_plain(
                gen,
                node,
                type_renderer,
                default_arguments,
            ),
            result_type=result_type,
            promote_result=bool(is_managed_type(gen, result_type)),
        )
        if sequenced is not None:
            return sequenced
    if node.op not in {"++", "--", "&", "*"}:
        sequenced = gen.ownership.sequence_operands(
            [node.operand],
            build=lambda: _lower_unary_plain(
                gen,
                node,
                type_renderer,
                default_arguments,
            ),
            result_type=gen.analyzed.node_types.get(id(node)),
        )
        if sequenced is not None:
            return sequenced
    return _lower_unary_plain(
        gen,
        node,
        type_renderer,
        default_arguments,
    )


def _lower_unary_plain(
    gen: IRLowerer,
    node: UnaryExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    from .expressions import lower_expr

    op = node.op
    if op in {"++", "--"}:
        from .updates import generator_update_context, lower_incdec

        return lower_incdec(
            generator_update_context(
                gen,
                type_renderer,
                default_arguments,
            ),
            node,
        )

    operand = lower_expr(
        gen,
        node.operand,
        type_renderer,
        default_arguments,
    )
    if op == "&":
        return IRAddressOf(expr=operand, source_expression=True)
    if op == "*":
        return IRDeref(expr=operand)
    # Operator overloading: -obj where obj is class with __neg__
    if op == "-" and node.prefix:
        operand_type = gen.analyzed.node_types.get(id(node.operand))
        if operand_type and operand_type.base in gen.analyzed.class_table:
            cls_info = gen.analyzed.class_table[operand_type.base]
            if "__neg__" in cls_info.methods:
                if operand_type.generic_args:
                    cls_c_name = gen.type_identity.specialization_symbol(
                        operand_type.base,
                        operand_type.generic_args,
                    )
                else:
                    cls_c_name = operand_type.base
                return IRCall(callee=f"{cls_c_name}___neg__", args=[operand])
    return IRUnaryOp(op=op, operand=operand, prefix=node.prefix)
