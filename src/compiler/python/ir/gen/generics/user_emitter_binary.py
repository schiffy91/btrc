"""Eager binary sequencing inside monomorphized generic methods."""

from ...nodes import IRBinOp
from ..operator_context import operator_context


def lower_generic_binary(emitter, expression):
    if expression.op in {"??", "&&", "||"}:
        return lower_generic_binary_plain(emitter, expression)

    from ..evaluation_order import has_observable_effect
    from ..operator_ownership import operator_rhs_keep
    from ..operators import overloaded_binary_method

    left_type = emitter._resolve_expr_type(expression.left)
    right_type = emitter._resolve_expr_type(expression.right)
    keep_nodes = (
        [expression.right]
        if operator_rhs_keep(
            emitter._gen,
            left_type,
            expression.op,
            right_type,
        )
        else []
    )
    pin_nodes = (
        [expression.left]
        if overloaded_binary_method(
            emitter._gen,
            left_type,
            expression.op,
        )
        is not None
        and emitter._is_managed_type(left_type)
        else []
    )
    sequenced = emitter._sequence_owned_nodes(
        [expression.left, expression.right],
        expression,
        lambda: lower_generic_binary_plain(emitter, expression),
        keep_nodes=keep_nodes,
        pin_nodes=pin_nodes,
        force=(
            has_observable_effect(
                emitter._gen,
                expression.left,
                type_of=emitter._resolve_expr_type,
            )
            or has_observable_effect(
                emitter._gen,
                expression.right,
                type_of=emitter._resolve_expr_type,
            )
        ),
    )
    if sequenced is not None:
        return sequenced
    return lower_generic_binary_plain(emitter, expression)


def lower_generic_binary_plain(emitter, expression):
    from ..operators import lower_overloaded_values
    from ..typed_operators import lower_typed_binary

    left = emitter._expr(expression.left)
    right = emitter._expr(expression.right)
    if expression.op == "??" and emitter._owns_expr(expression):
        from .user_emitter_ownership import normalize_owned_branch

        left = normalize_owned_branch(emitter, expression.left, left)
        right = normalize_owned_branch(emitter, expression.right, right)
    left_type = emitter._resolve_expr_type(expression.left)
    right_type = emitter._resolve_expr_type(expression.right)
    if emitter._gen:
        overloaded = lower_overloaded_values(
            emitter._gen,
            left_type,
            right_type,
            expression.op,
            left,
            right,
        )
        if overloaded is not None:
            return overloaded
    lowered = lower_typed_binary(
        expression.op,
        left,
        right,
        left_type,
        right_type,
        operator_context(emitter._gen, fresh_temp=emitter._fresh_temp),
    )
    if lowered is not None:
        return lowered
    return IRBinOp(left=left, op=expression.op, right=right)


__all__ = ["lower_generic_binary", "lower_generic_binary_plain"]
