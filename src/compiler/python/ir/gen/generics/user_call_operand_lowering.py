"""Lower generic-call operands after lifetime planning."""

from ..call_boundary import CallOperand
from ..evaluation_order import borrowed_value_can_be_pinned, operand_c_type
from ..projection_storage import evaluate_with_operand_overrides
from .user_call_arguments import (
    generic_call_argument_type,
    in_generic_call_argument_context,
    lower_generic_call_argument,
)


def lower_planned_generic_call_operands(
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
    from ..prepared_values import prepare_value

    operands = []
    final_index = len(specs) - 1
    spec_types = {id(node): type_expr for node, type_expr, *_rest in specs}
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
                emitter._type_renderer,
                receiver_node=receiver,
                resolve_argument_type=emitter._resolve_expr_type,
            )
            argument_type = target_type
            owned = emitter._is_managed_type(argument_type)
        elif target_type is not None:

            def prepare(
                argument=argument,
                param=param,
                is_default=is_default,
                target_type=target_type,
            ):
                return prepare_value(
                    emitter._gen,
                    argument,
                    target_type,
                    ownership=emitter._boundary_ownership,
                    lower_expr=lambda value: lower_generic_call_argument(
                        emitter,
                        param,
                        value,
                        is_default=is_default,
                    ),
                    type_of=lambda value: generic_call_argument_type(
                        emitter,
                        param,
                        value,
                        is_default=is_default,
                    ),
                    owns_result=lambda value: bool(
                        id(value) not in emitter._arc_overrides
                        and in_generic_call_argument_context(
                            emitter,
                            param,
                            is_default,
                            lambda value=value: emitter._owns_expr(value),
                        )
                    ),
                    render_type=emitter.iter_value_c,
                    activate_cleanup=emitter._activate_cleanup_registration,
                )

            if id(argument) in deferred:

                def lower_prepared(overrides, prepare=prepare):
                    return evaluate_with_operand_overrides(
                        overrides,
                        values=emitter._arc_overrides,
                        types=spec_types,
                        type_values=emitter._arc_type_overrides,
                        operation=lambda: prepare().value,
                    )

                lower_with_overrides = lower_prepared
            else:
                prepared = prepare()
                argument_type = prepared.effective_type
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
                    values=emitter._arc_overrides,
                    types=spec_types,
                    type_values=emitter._arc_type_overrides,
                    operation=lambda: lower_generic_call_argument(
                        emitter,
                        param,
                        argument,
                        is_default=is_default,
                    ),
                )

            lower_with_overrides = lower_direct
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


__all__ = ["lower_planned_generic_call_operands"]
