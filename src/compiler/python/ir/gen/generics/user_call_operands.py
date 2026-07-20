"""Call-operand planning for monomorphized generic methods."""

from ..arguments import bind_arg_nodes_to_params
from ..call_boundary import CallOperand
from ..evaluation_order import (
    borrowed_value_can_be_pinned,
    has_observable_effect,
    operand_c_type,
)
from .user_call_arguments import (
    generic_call_argument_type,
    in_generic_call_argument_context,
    lower_generic_call_argument,
)


def generic_call_operands(
    emitter,
    params,
    ast_args,
    arg_names,
    receiver,
    transferred_params=frozenset(),
    *,
    callee=None,
    pin_receiver=False,
    force_order=True,
    call=None,
):
    """Plan concrete, source-ordered operands for one generic call."""
    if not emitter._gen:
        return []
    bindings = bind_arg_nodes_to_params(params, ast_args, arg_names)
    from ..default_argument_calls import bound_nodes_by_parameter

    bound_nodes = bound_nodes_by_parameter(params, bindings)
    specs = []
    for value in (callee, receiver):
        if value is None:
            continue
        value_type = emitter._resolve_expr_type(value)
        value_owned = bool(emitter._is_managed_type(value_type) and emitter._owns_expr(value))
        specs.append(
            (
                value,
                value_type,
                None,
                bool(value is receiver and pin_receiver),
                value_owned,
                False,
                None,
                False,
                None,
            )
        )
    from ..hosted_result_conversion import (
        REJECT,
        hosted_string_conversion_mode,
        requires_target_value_conversion,
    )

    for param_index, argument, is_default in bindings:
        param = params[param_index] if param_index is not None and param_index < len(params) else None
        if is_default and param is not None:
            target_type = param.type
            managed = emitter._is_managed_type(target_type)
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
        source_type = generic_call_argument_type(
            emitter,
            param,
            argument,
            is_default=is_default,
        )
        target_type = param.type if param is not None else source_type
        if (
            hosted_string_conversion_mode(
                emitter._gen,
                argument,
                target_type,
                source_type,
            )
            == REJECT
            and param is not None
            and not param.keep
            and param_index not in transferred_params
        ):
            target_type = source_type
        converted = requires_target_value_conversion(
            emitter._gen,
            argument,
            target_type,
            source_type,
        )
        argument_type = target_type if converted else (source_type or target_type)
        managed = emitter._is_managed_type(argument_type)
        owned = bool(
            managed
            and (
                converted
                or in_generic_call_argument_context(
                    emitter,
                    param,
                    is_default,
                    lambda argument=argument: emitter._owns_expr(argument),
                )
            )
        )
        specs.append(
            (
                argument,
                argument_type,
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
                emitter._gen,
                argument,
                target_type,
                generic_call_argument_type(
                    emitter,
                    param,
                    argument,
                    is_default=is_default,
                ),
            )
        )
        or has_observable_effect(
            emitter._gen,
            argument,
            type_of=lambda value, param=param, is_default=is_default: generic_call_argument_type(
                emitter,
                param,
                value,
                is_default=is_default,
            ),
        )
        for argument, _type, target_type, _keep, _owned, _transferred, param, is_default, _index in specs
    ]
    ownership_required = any(
        keep or owned for _argument, _type, _target, keep, owned, _transferred, _param, _default, _index in specs
    )
    types_complete = all(
        type_expr is not None
        for _argument, type_expr, _target, _keep, _owned, _transferred, _param, _default, _index in specs
    )
    has_default = any(spec[-2] for spec in specs)
    if (
        not has_default
        and not ownership_required
        and not (force_order and len(specs) > 1 and types_complete and any(effects))
    ):
        return []
    return _lower_operands(
        emitter,
        specs,
        effects,
        call=call,
        params=params,
        bound_nodes=bound_nodes,
        receiver=receiver,
    )


def _lower_operands(
    emitter,
    specs,
    effects,
    *,
    call,
    params,
    bound_nodes,
    receiver,
):
    from ..prepared_values import prepare_value

    operands = []
    final_index = len(specs) - 1
    for index, (
        argument,
        argument_type,
        target_type,
        keep,
        owned,
        transferred,
        param,
        is_default,
        param_index,
    ) in enumerate(specs):
        emitter._require_operand_type(argument_type)
        pin = bool(
            borrowed_value_can_be_pinned(argument)
            and index < final_index
            and any(effects[index + 1 :])
            and emitter._is_managed_type(argument_type)
            and not owned
        )
        prepared = None
        lower_with_overrides = None
        if is_default:
            if call is None or param_index is None:
                from ..errors import CodegenError

                raise CodegenError("default argument lowering requires a resolved call target")
            from ..default_argument_calls import default_call_builder

            lower_with_overrides = default_call_builder(
                emitter._gen,
                call,
                params,
                param_index,
                bound_nodes,
                receiver_node=receiver,
                resolve_argument_type=emitter._resolve_expr_type,
            )
            argument_type = target_type
            owned = emitter._is_managed_type(argument_type)
        elif target_type is not None:
            prepared = prepare_value(
                emitter._gen,
                argument,
                target_type,
                lower_expr=lambda value, param=param, is_default=is_default: lower_generic_call_argument(
                    emitter,
                    param,
                    value,
                    is_default=is_default,
                ),
                type_of=lambda value, param=param, is_default=is_default: generic_call_argument_type(
                    emitter,
                    param,
                    value,
                    is_default=is_default,
                ),
                owns_result=lambda value, param=param, is_default=is_default: bool(
                    id(value) not in emitter._arc_overrides
                    and in_generic_call_argument_context(
                        emitter,
                        param,
                        is_default,
                        lambda value=value: emitter._owns_expr(value),
                    )
                ),
                render_type=emitter.iter_value_c,
                fresh_temp=emitter._fresh_temp,
                cleanup_active=emitter._exception_cleanup_active(),
                record_decl=emitter._func_var_decls.append,
                activate_cleanup=emitter._activate_cleanup_registration,
            )
            argument_type = prepared.effective_type
            owned = prepared.owned
        operands.append(
            CallOperand(
                node=argument,
                type_expr=argument_type,
                c_type=(
                    emitter.iter_value_c(argument_type)
                    if prepared is not None or lower_with_overrides is not None
                    else operand_c_type(
                        emitter._gen,
                        argument,
                        argument_type,
                        render=emitter.iter_value_c,
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


__all__ = ["generic_call_operands"]
