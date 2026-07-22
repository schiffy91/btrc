"""Call-operand planning for monomorphized generic methods."""

from ..arguments import bind_arg_nodes_to_params
from ..evaluation_order import (
    has_observable_effect,
)
from .user_call_arguments import (
    generic_call_argument_type,
    in_generic_call_argument_context,
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
    if not emitter._gen or emitter._unevaluated_depth > 0:
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

    def spec_has_effect(spec):
        argument, _type, target_type, _keep, _owned, _transferred, param, is_default, _index = spec
        return (
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
        )

    source_effects = [spec_has_effect(spec) for spec in specs]
    from ....hosted_alias_carriers import hosted_alias_argument
    from ..call_projection_operands import (
        expand_projection_owner_specs,
        readonly_hosted_borrow_needs_no_guard,
    )
    from ..projection_storage import projection_storage_operands

    specs, deferred = expand_projection_owner_specs(
        specs,
        owners_for=lambda expression: projection_storage_operands(
            expression,
            type_of=emitter._resolve_expr_type,
            is_managed=emitter._is_managed_type,
            owns=emitter._owns_expr,
            overridden=lambda value: id(value) in emitter._arc_overrides,
            struct_table=emitter._gen.analyzed.struct_table,
            return_alias_argument=lambda value: hosted_alias_argument(
                value,
                emitter._gen.analyzed.hosted_call_ids,
            ),
        ),
        type_of=emitter._resolve_expr_type,
        omit_borrowed_guard=lambda spec, index: readonly_hosted_borrow_needs_no_guard(
            call,
            spec[-1],
            has_later_effects=any(source_effects[index + 1 :]),
            hosted_call_ids=emitter._gen.analyzed.hosted_call_ids,
        ),
    )
    effects = [spec_has_effect(spec) for spec in specs]
    ownership_required = bool(deferred) or any(
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
        deferred,
        call=call,
        params=params,
        bound_nodes=bound_nodes,
        receiver=receiver,
    )


def _lower_operands(
    emitter,
    specs,
    effects,
    deferred,
    *,
    call,
    params,
    bound_nodes,
    receiver,
):
    from .user_call_operand_lowering import (
        lower_planned_generic_call_operands,
    )

    return lower_planned_generic_call_operands(
        emitter,
        specs,
        effects,
        deferred,
        call=call,
        params=params,
        bound_nodes=bound_nodes,
        receiver=receiver,
    )


__all__ = ["generic_call_operands"]
