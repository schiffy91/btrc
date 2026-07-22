"""Source-order and lifetime planning for ordinary call operands."""

from .call_callees import callable_callee_type
from .default_argument_context import (
    call_argument_type,
    in_call_argument_context,
)
from .ownership import owns_result


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
    if getattr(gen, "_unevaluated_depth", 0) > 0:
        return [], False
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
        if type_expr is None:
            type_expr = callable_callee_type(gen, value)
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

    def spec_has_effect(spec):
        argument, _type_expr, target_type, _keep, _owned, _transferred, param, is_default, _index = spec
        return (
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
        )

    source_effects = [spec_has_effect(spec) for spec in specs]
    from ...hosted_alias_carriers import hosted_alias_argument
    from .call_projection_operands import (
        expand_projection_owner_specs,
        readonly_hosted_borrow_needs_no_guard,
    )
    from .projection_storage import projection_storage_operands

    def projection_owners(expression):
        if default_receiver_value is not None and expression is callee:
            return []
        return projection_storage_operands(
            expression,
            type_of=lambda value: gen.analyzed.node_types.get(id(value)),
            is_managed=lambda type_expr: is_managed_type(gen, type_expr),
            owns=lambda value: owns_result(gen, value),
            overridden=lambda value: id(value) in gen._owning_temp_overrides,
            struct_table=gen.analyzed.struct_table,
            return_alias_argument=lambda value: hosted_alias_argument(
                value,
                gen.analyzed.hosted_call_ids,
            ),
        )

    specs, deferred = expand_projection_owner_specs(
        specs,
        owners_for=projection_owners,
        type_of=lambda value: gen.analyzed.node_types.get(id(value)),
        omit_borrowed_guard=lambda spec, index: readonly_hosted_borrow_needs_no_guard(
            call,
            spec[-1],
            has_later_effects=any(source_effects[index + 1 :]),
            hosted_call_ids=gen.analyzed.hosted_call_ids,
        ),
    )
    effects = [spec_has_effect(spec) for spec in specs]
    ownership_required = bool(deferred) or any(
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
            deferred,
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
    deferred,
    *,
    call,
    params,
    bound_nodes,
    receiver,
    default_receiver_value,
):
    from .call_operand_lowering import lower_planned_call_operands

    return lower_planned_call_operands(
        gen,
        specs,
        effects,
        deferred,
        call=call,
        params=params,
        bound_nodes=bound_nodes,
        receiver=receiver,
        default_receiver_value=default_receiver_value,
    )


__all__ = ["plan_call_operands"]
