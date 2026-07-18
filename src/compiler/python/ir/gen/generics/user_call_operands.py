"""Call-operand planning for monomorphized generic methods."""

from ..arguments import bind_arg_nodes_to_params
from ..call_boundary import CallOperand
from ..evaluation_order import (
    borrowed_value_can_be_pinned,
    has_observable_effect,
    operand_c_type,
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
):
    """Plan concrete, source-ordered operands for one generic call."""
    if not emitter._gen:
        return []
    bindings = bind_arg_nodes_to_params(params, ast_args, arg_names)
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
            )
        )
    from ..prepared_values import requires_string_conversion

    for param_index, argument, _is_default in bindings:
        param = params[param_index] if param_index is not None and param_index < len(params) else None
        source_type = emitter._resolve_expr_type(argument)
        target_type = param.type if param is not None else source_type
        converted = requires_string_conversion(
            emitter._gen,
            target_type,
            source_type,
        )
        argument_type = target_type if converted else (source_type or target_type)
        managed = emitter._is_managed_type(argument_type)
        owned = bool(managed and (converted or emitter._owns_expr(argument)))
        specs.append(
            (
                argument,
                argument_type,
                target_type,
                bool(managed and param is not None and param.keep),
                owned,
                bool(owned and param_index in transferred_params),
            )
        )
    effects = [
        bool(
            target_type is not None
            and requires_string_conversion(
                emitter._gen,
                target_type,
                emitter._resolve_expr_type(argument),
            )
        )
        or has_observable_effect(
            emitter._gen,
            argument,
            type_of=emitter._resolve_expr_type,
        )
        for argument, _type, target_type, _keep, _owned, _transferred in specs
    ]
    ownership_required = any(keep or owned for _argument, _type, _target, keep, owned, _transferred in specs)
    types_complete = all(type_expr is not None for _argument, type_expr, _target, _keep, _owned, _transferred in specs)
    if not ownership_required and not (force_order and len(specs) > 1 and types_complete and any(effects)):
        return []
    return _lower_operands(
        emitter,
        specs,
        effects,
    )


def _lower_operands(emitter, specs, effects):
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
        if target_type is not None:
            prepared = prepare_value(
                emitter._gen,
                argument,
                target_type,
                lower_expr=emitter._expr,
                type_of=emitter._resolve_expr_type,
                owns_result=lambda value: bool(id(value) not in emitter._arc_overrides and emitter._owns_expr(value)),
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
                    if prepared is not None
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
            )
        )
    return operands


__all__ = ["generic_call_operands"]
