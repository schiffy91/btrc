"""Call-scoped ownership planning for the primary IR generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier, LambdaExpr
from ...string_methods import STRING_METHODS
from .call_boundary import sequence_call_boundary
from .call_operand_planning import plan_call_operands
from .ownership import owns_result
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_call_with_arc(gen: IRGenerator, node: CallExpr):
    """Lower a call with single-evaluation, call-scoped ARC guards."""
    from .aggregate_ownership import reject_rich_enum_owned_args
    from .call_effects import (
        callable_for_call,
        owned_transfer_param_indices,
    )
    from .callable_boundaries import reject_unsafe_managed_callback_arguments
    from .calls import _lower_call

    reject_rich_enum_owned_args(gen, node)
    reject_unsafe_managed_callback_arguments(gen, node)
    if isinstance(node.callee, FieldAccessExpr) and node.callee.optional:
        return _lower_call(gen, node)

    declaration = callable_for_call(gen, node)
    from .call_contracts import resolved_params_for_call

    params = resolved_params_for_call(gen, node)
    from .hosted_result_conversion import (
        lower_hosted_string_conversion,
        requested_hosted_string_conversion,
    )

    result_conversion = requested_hosted_string_conversion(gen, node)
    callable_field = _callable_field(gen, node)
    receiver = None if callable_field else _instance_receiver(gen, node)
    from .receiver_pinning import receiver_pin_required

    operands, needs_boundary = plan_call_operands(
        gen,
        params,
        node.args,
        _arg_names(node),
        receiver=receiver,
        callee=node.callee if callable_field else _evaluated_callee(node),
        transferred_params=owned_transfer_param_indices(declaration),
        pin_receiver=receiver_pin_required(
            gen,
            receiver,
            declared_call=declaration is not None,
            owned_local_type=gen.managed_local_type,
        ),
        force_order=_language_ordered_call(gen, node, declaration),
        call=node,
    )
    if not needs_boundary:
        call = _lower_call(gen, node)
        if result_conversion is not None:
            call = lower_hosted_string_conversion(
                gen,
                call,
                result_conversion[0],
            )
        return call

    result_type = result_conversion[1] if result_conversion is not None else gen.analyzed.node_types.get(id(node))

    def build_call(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        try:
            call = _lower_call(gen, node)
            if result_conversion is not None:
                call = lower_hosted_string_conversion(
                    gen,
                    call,
                    result_conversion[0],
                )
            return call
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value

    return sequence_call_boundary(
        gen,
        operands,
        lower_expr=_lowerer(gen),
        build_call=build_call,
        result_c_type=type_to_c(result_type) if result_type is not None else None,
        result_type=result_type,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
        promote_result=False,
        result_owned=bool(result_conversion is not None or owns_result(gen, node)),
    )


def _arg_names(node):
    from .arguments import arg_names_for

    return arg_names_for(node, len(node.args))


def _instance_receiver(gen, node):
    if not isinstance(node.callee, FieldAccessExpr):
        return None
    receiver = node.callee.obj
    if isinstance(receiver, Identifier) and (
        receiver.name in gen.analyzed.class_table or receiver.name in gen.analyzed.rich_enum_table
    ):
        return None
    return receiver


def _evaluated_callee(node):
    """Return a side-effecting callable value that precedes call arguments."""
    callee = node.callee
    if isinstance(callee, (Identifier, FieldAccessExpr, LambdaExpr)):
        return None
    return callee


def _callable_field(gen, node) -> bool:
    if not isinstance(node.callee, FieldAccessExpr):
        return False
    from .callable_fields import callable_field_signature

    return callable_field_signature(gen, node.callee) is not None


def _language_ordered_call(gen, node, declaration) -> bool:
    if declaration is not None:
        return True
    if id(node) in gen.analyzed.hosted_call_ids:
        return True
    if isinstance(node.callee, Identifier) and node.callee.name in {
        "print",
        "printf",
        "Mutex",
    }:
        return True
    if isinstance(node.callee, FieldAccessExpr):
        if isinstance(node.callee.obj, Identifier) and node.callee.obj.name in gen.analyzed.rich_enum_table:
            return True
        from .type_resolution import canonical_type
        from .types import is_string_type

        receiver_type = canonical_type(
            gen.analyzed.node_types.get(id(node.callee.obj)),
            gen.analyzed.typedef_table,
        )
        if is_string_type(receiver_type) and node.callee.field in STRING_METHODS:
            return True
        from .managed_values import is_mutex_type

        receiver_type = gen.analyzed.node_types.get(id(node.callee.obj))
        if is_mutex_type(gen, receiver_type):
            return True
    callee_type = gen.analyzed.node_types.get(id(node.callee))
    return bool(callee_type is not None and callee_type.base == "__fn_ptr")


def _lowerer(gen):
    from .expressions import lower_expr

    return lambda node: lower_expr(gen, node)


__all__ = ["lower_call_with_arc", "plan_call_operands"]
