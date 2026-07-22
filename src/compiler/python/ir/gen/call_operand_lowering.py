"""Lower ordinary call operands after lifetime planning."""

from .call_boundary import CallOperand
from .call_operand_diagnostics import missing_default_target, missing_operand_type
from .default_argument_context import (
    call_argument_type,
    in_call_argument_context,
    lower_call_argument,
)
from .projection_storage import evaluate_with_operand_overrides
from .types import type_to_c


def lower_planned_call_operands(
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
    from .evaluation_order import borrowed_value_can_be_pinned, operand_c_type
    from .managed_values import is_managed_type
    from .ownership import owns_result
    from .prepared_values import prepare_value

    operands = []
    final_index = len(specs) - 1
    spec_types = {id(node): type_expr for node, type_expr, *_rest in specs}
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

            def prepare(
                argument=argument,
                param=param,
                is_default=is_default,
                target_type=target_type,
            ):
                return prepare_value(
                    gen,
                    argument,
                    target_type,
                    lower_expr=lambda value: lower_call_argument(
                        gen,
                        param,
                        value,
                        is_default=is_default,
                    ),
                    type_of=lambda value: call_argument_type(
                        gen,
                        param,
                        value,
                        is_default=is_default,
                    ),
                    owns_result=lambda value: bool(
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

            if id(argument) in deferred:

                def lower_prepared(overrides, prepare=prepare):
                    return evaluate_with_operand_overrides(
                        overrides,
                        values=gen._owning_temp_overrides,
                        types=spec_types,
                        type_values=gen._type_temp_overrides,
                        operation=lambda: prepare().value,
                    )

                lower_with_overrides = lower_prepared
            else:
                prepared = prepare()
                type_expr = prepared.effective_type
                owned = prepared.owned
        elif id(argument) in deferred:

            def lower_direct(
                overrides,
                argument=argument,
                param=param,
                is_default=is_default,
            ):
                return evaluate_with_operand_overrides(
                    overrides,
                    values=gen._owning_temp_overrides,
                    types=spec_types,
                    type_values=gen._type_temp_overrides,
                    operation=lambda: lower_call_argument(
                        gen,
                        param,
                        argument,
                        is_default=is_default,
                    ),
                )

            lower_with_overrides = lower_direct
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


__all__ = ["lower_planned_call_operands"]
