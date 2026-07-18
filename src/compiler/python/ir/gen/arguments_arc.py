"""Call-scoped ownership planning for the primary IR generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier, LambdaExpr
from ...string_methods import STRING_METHODS
from .call_boundary import CallOperand, sequence_call_boundary
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
    from .calls import _lower_call

    reject_rich_enum_owned_args(gen, node)
    if isinstance(node.callee, FieldAccessExpr) and node.callee.optional:
        return _lower_call(gen, node)

    declaration = callable_for_call(gen, node)
    from .call_contracts import resolved_params_for_call

    params = resolved_params_for_call(gen, node)
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
    )
    if not needs_boundary:
        return _lower_call(gen, node)

    result_type = gen.analyzed.node_types.get(id(node))

    def build_call(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        try:
            return _lower_call(gen, node)
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
        result_owned=owns_result(gen, node),
    )


def plan_call_operands(
    gen,
    params,
    ast_args,
    arg_names,
    *,
    receiver=None,
    callee=None,
    transferred_params=frozenset(),
    pin_receiver: bool = False,
    force_order: bool = True,
):
    """Describe one call's source-order operands and lifetime guards."""
    from .arguments import bind_arg_nodes_to_params
    from .evaluation_order import (
        borrowed_value_can_be_pinned,
        has_observable_effect,
        operand_c_type,
        operands_require_order,
    )
    from .managed_values import is_managed_type

    specs = []
    for value in (callee, receiver):
        if value is None:
            continue
        type_expr = gen.analyzed.node_types.get(id(value))
        managed = is_managed_type(gen, type_expr)
        specs.append(
            (
                value,
                type_expr,
                None,
                bool(value is receiver and pin_receiver),
                bool(managed and owns_result(gen, value)),
                False,
            )
        )
    from .prepared_values import requires_string_conversion

    for param_index, argument, _is_default in bind_arg_nodes_to_params(params, ast_args, arg_names):
        param = params[param_index] if param_index is not None and 0 <= param_index < len(params) else None
        source_type = gen.analyzed.node_types.get(id(argument))
        target_type = param.type if param is not None else source_type
        converted = requires_string_conversion(gen, target_type, source_type)
        effective_type = target_type if converted else (source_type or target_type)
        managed = is_managed_type(gen, effective_type)
        owned = bool(managed and (converted or owns_result(gen, argument)))
        specs.append(
            (
                argument,
                effective_type,
                target_type,
                bool(managed and param is not None and param.keep),
                owned,
                bool(owned and param_index in transferred_params),
            )
        )
    effects = [
        bool(
            target_type is not None
            and requires_string_conversion(gen, target_type, gen.analyzed.node_types.get(id(argument)))
        )
        or has_observable_effect(gen, argument)
        for argument, _type_expr, target_type, _keep, _owned, _transferred in specs
    ]
    ownership_required = any(keep or owned for _argument, _type_expr, _target, keep, owned, _transferred in specs)
    ordered = force_order and operands_require_order(
        gen,
        [argument for argument, _type_expr, _target, _keep, _owned, _transferred in specs],
    )
    needs_boundary = ownership_required or ordered
    if not needs_boundary:
        return [], False

    operands = []
    final_index = len(specs) - 1
    from .expressions import lower_expr
    from .prepared_values import prepare_value

    for index, (argument, type_expr, target_type, keep, owned, transferred) in enumerate(specs):
        if type_expr is None:
            if index == final_index and index > 0 and not (keep or owned):
                continue
            _missing_operand_type(argument)
        pin = bool(
            borrowed_value_can_be_pinned(argument)
            and index < final_index
            and any(effects[index + 1 :])
            and is_managed_type(gen, type_expr)
            and not owned
        )
        prepared = None
        if target_type is not None:
            prepared = prepare_value(
                gen,
                argument,
                target_type,
                lower_expr=lambda value: lower_expr(gen, value),
                type_of=lambda value: gen.analyzed.node_types.get(id(value)),
                owns_result=lambda value: bool(id(value) not in gen._owning_temp_overrides and owns_result(gen, value)),
                render_type=type_to_c,
                fresh_temp=gen.fresh_temp,
                cleanup_active=gen.exception_cleanup_active(),
                record_decl=gen._func_var_decls.append,
            )
            type_expr = prepared.effective_type
            owned = prepared.owned
        operands.append(
            CallOperand(
                node=argument,
                type_expr=type_expr,
                c_type=(
                    type_to_c(type_expr)
                    if prepared is not None
                    else operand_c_type(gen, argument, type_expr, render=type_to_c)
                ),
                keep=keep,
                pin=pin,
                owned=owned,
                transferred=transferred,
                lowered=prepared.value if prepared is not None else None,
            )
        )
    return operands, True


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


def _missing_operand_type(argument):
    from .evaluation_order import reject_opaque_ordering

    reject_opaque_ordering(
        argument,
        "call arguments",
        typed_declaration=True,
    )


__all__ = ["lower_call_with_arc", "plan_call_operands"]
