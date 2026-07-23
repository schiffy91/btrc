"""Eager binary sequencing inside monomorphized generic methods."""

from ...nodes import IRBinOp
from ..operator_context import operator_context


def lower_generic_binary(emitter, expression):
    if expression.op in {"??", "&&", "||"}:
        return lower_generic_binary_plain(emitter, expression)

    prepared = _lower_prepared_overload(emitter, expression)
    if prepared is not None:
        return prepared

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
            emitter._type_renderer,
        )
        if overloaded is not None:
            return overloaded
    lowered = lower_typed_binary(
        expression.op,
        left,
        right,
        left_type,
        right_type,
        operator_context(
            emitter._gen,
            emitter._type_renderer,
            fresh_temp=emitter._fresh_temp,
        ),
    )
    if lowered is not None:
        return lowered
    return IRBinOp(left=left, op=expression.op, right=right)


def _lower_prepared_overload(emitter, expression):
    if emitter._gen is None:
        return None
    from ..operators import (
        lower_overloaded_values,
        overloaded_binary_method,
        resolved_operator_param_type,
    )
    from ..prepared_values import (
        prepare_generic_value,
        requires_string_conversion,
    )

    left_type = emitter._resolve_expr_type(expression.left)
    right_type = emitter._resolve_expr_type(expression.right)
    method = overloaded_binary_method(
        emitter._gen,
        left_type,
        expression.op,
    )
    expected = resolved_operator_param_type(emitter._gen, left_type, method)
    if expected is not None:
        expected = emitter._resolve(expected)
    if expected is None or not requires_string_conversion(
        emitter._gen,
        expected,
        right_type,
    ):
        return None

    left = prepare_generic_value(emitter, expression.left, left_type)
    right = prepare_generic_value(emitter, expression.right, expected)
    from ..call_boundary import CallOperand
    from ..evaluation_order import borrowed_value_can_be_pinned

    operands = [
        CallOperand(
            node=expression.left,
            type_expr=left.effective_type,
            c_type=emitter.iter_value_c(left.effective_type),
            pin=bool(
                borrowed_value_can_be_pinned(expression.left)
                and emitter._is_managed_type(left.effective_type)
                and not left.owned
            ),
            owned=left.owned,
            lowered=left.value,
        ),
        CallOperand(
            node=expression.right,
            type_expr=right.effective_type,
            c_type=emitter.iter_value_c(right.effective_type),
            keep=bool(method.params[0].keep),
            owned=right.owned,
            lowered=right.value,
        ),
    ]
    result_type = emitter._resolve_expr_type(expression)
    return emitter._boundary_ownership.boundaries.sequence(
        operands,
        lower_expr=lambda _node: None,
        build_call=lambda values: lower_overloaded_values(
            emitter._gen,
            left.effective_type,
            right.effective_type,
            expression.op,
            values[id(expression.left)],
            values[id(expression.right)],
            emitter._type_renderer,
        ),
        result_c_type=emitter.iter_value_c(result_type),
        result_type=result_type,
        activate_cleanup=emitter._activate_cleanup_registration,
        result_owned=emitter._owns_expr(expression),
    )


__all__ = ["lower_generic_binary", "lower_generic_binary_plain"]
