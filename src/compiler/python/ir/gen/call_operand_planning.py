"""Source-order and lifetime planning for ordinary call operands."""

from .call_boundary import CallOperand
from .call_operand_diagnostics import missing_default_target, missing_operand_type
from .default_argument_context import (
    call_argument_type,
    in_call_argument_context,
    lower_call_argument,
)
from .ownership import owns_result
from .types import type_to_c


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
    call=None,
    default_receiver_value=None,
):
    """Describe one call's source-order operands and lifetime guards."""
    from .arguments import bind_arg_nodes_to_params
    from .evaluation_order import (
        has_observable_effect,
        operands_require_order,
    )
    from .managed_values import is_managed_type

    bindings = bind_arg_nodes_to_params(params, ast_args, arg_names)
    from .default_argument_calls import bound_nodes_by_parameter

    bound_nodes = bound_nodes_by_parameter(params, bindings)
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
                None,
                False,
                None,
            )
        )
    from .hosted_result_conversion import (
        REJECT,
        hosted_string_conversion_mode,
        requires_target_value_conversion,
    )

    for param_index, argument, is_default in bindings:
        param = params[param_index] if param_index is not None and 0 <= param_index < len(params) else None
        if is_default and param is not None:
            target_type = param.type
            managed = is_managed_type(gen, target_type)
            specs.append(
                (
                    argument,
                    target_type,
                    target_type,
                    bool(managed and param.keep),
                    bool(managed),
                    bool(managed and param_index in transferred_params),
                    param,
                    True,
                    param_index,
                )
            )
            continue
        source_type = call_argument_type(
            gen,
            param,
            argument,
            is_default=is_default,
        )
        target_type = param.type if param is not None else source_type
        if (
            hosted_string_conversion_mode(
                gen,
                argument,
                target_type,
                source_type,
            )
            == REJECT
            and param is not None
            and not param.keep
            and param_index not in transferred_params
        ):
            # Proven borrow-only source parameters may observe a raw C string
            # ephemerally without turning it into managed storage.
            target_type = source_type
        converted = requires_target_value_conversion(
            gen,
            argument,
            target_type,
            source_type,
        )
        effective_type = target_type if converted else (source_type or target_type)
        managed = is_managed_type(gen, effective_type)
        owned = bool(
            managed
            and (
                converted
                or in_call_argument_context(
                    param,
                    is_default,
                    lambda argument=argument: owns_result(gen, argument),
                )
            )
        )
        specs.append(
            (
                argument,
                effective_type,
                target_type,
                bool(managed and param is not None and param.keep),
                owned,
                bool(owned and param_index in transferred_params),
                param,
                is_default,
                param_index,
            )
        )
    effects = [
        is_default
        or bool(
            target_type is not None
            and requires_target_value_conversion(
                gen,
                argument,
                target_type,
                call_argument_type(
                    gen,
                    param,
                    argument,
                    is_default=is_default,
                ),
            )
        )
        or has_observable_effect(gen, argument)
        for argument, _type_expr, target_type, _keep, _owned, _transferred, param, is_default, _index in specs
    ]
    ownership_required = any(
        keep or owned for _argument, _type_expr, _target, keep, owned, _transferred, _param, _default, _index in specs
    )
    ordered = force_order and operands_require_order(
        gen,
        [argument for argument, _type_expr, _target, _keep, _owned, _transferred, _param, _default, _index in specs],
    )
    has_default = any(spec[-2] for spec in specs)
    if not (ownership_required or ordered or has_default):
        return [], False
    return (
        _lower_operands(
            gen,
            specs,
            effects,
            call=call,
            params=params,
            bound_nodes=bound_nodes,
            receiver=receiver,
            default_receiver_value=default_receiver_value,
        ),
        True,
    )


def _lower_operands(
    gen,
    specs,
    effects,
    *,
    call,
    params,
    bound_nodes,
    receiver,
    default_receiver_value,
):
    from .evaluation_order import borrowed_value_can_be_pinned, operand_c_type
    from .managed_values import is_managed_type
    from .prepared_values import prepare_value

    operands = []
    final_index = len(specs) - 1
    for index, (
        argument,
        type_expr,
        target_type,
        keep,
        owned,
        transferred,
        param,
        is_default,
        param_index,
    ) in enumerate(specs):
        if type_expr is None:
            if index == final_index and index > 0 and not (keep or owned):
                continue
            missing_operand_type(argument)
        pin = bool(
            borrowed_value_can_be_pinned(argument)
            and index < final_index
            and any(effects[index + 1 :])
            and is_managed_type(gen, type_expr)
            and not owned
        )
        prepared = None
        lower_with_overrides = None
        if is_default:
            if call is None or param_index is None:
                missing_default_target()
            from .default_argument_calls import default_call_builder

            lower_with_overrides = default_call_builder(
                gen,
                call,
                params,
                param_index,
                bound_nodes,
                receiver_node=receiver,
                receiver_value=default_receiver_value,
            )
            type_expr = target_type
            owned = is_managed_type(gen, type_expr)
        elif target_type is not None:
            prepared = prepare_value(
                gen,
                argument,
                target_type,
                lower_expr=lambda value, param=param, is_default=is_default: lower_call_argument(
                    gen,
                    param,
                    value,
                    is_default=is_default,
                ),
                type_of=lambda value, param=param, is_default=is_default: call_argument_type(
                    gen,
                    param,
                    value,
                    is_default=is_default,
                ),
                owns_result=lambda value, param=param, is_default=is_default: bool(
                    id(value) not in gen._owning_temp_overrides
                    and in_call_argument_context(
                        param,
                        is_default,
                        lambda value=value: owns_result(gen, value),
                    )
                ),
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
                    if prepared is not None or lower_with_overrides is not None
                    else operand_c_type(
                        gen,
                        argument,
                        type_expr,
                        render=type_to_c,
                    )
                ),
                keep=keep,
                pin=pin,
                owned=owned,
                transferred=transferred,
                lowered=prepared.value if prepared is not None else None,
                lower_with_overrides=lower_with_overrides,
            )
        )
    return operands


__all__ = ["plan_call_operands"]
