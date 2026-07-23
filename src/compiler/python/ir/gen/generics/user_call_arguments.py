"""Target-resolved argument contracts for generic method emission."""

from __future__ import annotations

from ..call_parameter_contract import resolved_parameter


def resolved_generic_parameters(emitter, params, substitutions=None):
    """Resolve parameter types and retain substitutions for default lowering."""
    concrete = {name: emitter._resolve(value) for name, value in (substitutions or {}).items()}
    from ..type_resolution import substitute_concrete_type

    return [
        resolved_parameter(
            param,
            emitter._resolve(
                substitute_concrete_type(
                    param.type,
                    concrete,
                    emitter._typedefs(),
                )
            ),
            concrete,
        )
        for param in params
    ]


def call_target_substitutions(emitter, expression):
    """Return concrete class/method substitutions owned by a call target."""
    from ....ast_nodes import FieldAccessExpr, Identifier

    callee = expression.callee
    if isinstance(callee, Identifier):
        class_info = emitter._gen.analyzed.class_table.get(callee.name)
        instance = emitter._resolve_expr_type(expression)
        if class_info and instance and class_info.generic_params:
            return dict(zip(class_info.generic_params, instance.generic_args))
        return {}
    if not isinstance(callee, FieldAccessExpr):
        return {}
    receiver = emitter._resolve_expr_type(callee.obj)
    class_info = emitter._gen.analyzed.class_table.get(receiver.base) if receiver is not None else None
    substitutions = dict(zip(class_info.generic_params, receiver.generic_args)) if class_info else {}
    method = class_info.methods.get(callee.field) if class_info else None
    method_args = emitter._gen.analyzed.generic_method_call_args.get(
        id(expression),
        (),
    )
    if method and method.generic_params:
        substitutions.update(zip(method.generic_params, method_args))
    return substitutions


def lower_generic_call_argument(emitter, param, node, *, is_default=False):
    return _in_parameter_context(
        emitter,
        param,
        is_default,
        lambda: emitter._expr(node),
    )


def generic_call_argument_type(emitter, param, node, *, is_default=False):
    return _in_parameter_context(
        emitter,
        param,
        is_default,
        lambda: emitter._resolve_expr_type(node),
    )


def in_generic_call_argument_context(
    emitter,
    param,
    is_default,
    operation,
):
    return _in_parameter_context(
        emitter,
        param,
        is_default,
        operation,
    )


def _in_parameter_context(emitter, param, is_default, operation):
    substitutions = getattr(param, "default_type_map", None) if is_default and param is not None else None
    if not substitutions:
        return operation()
    previous = emitter.type_map
    emitter.type_map = {**previous, **substitutions}
    try:
        return operation()
    finally:
        emitter.type_map = previous


def order_generic_call_arguments(
    emitter,
    params,
    ast_args,
    arg_names,
    ir_args,
):
    """Bind source operands to resolved slots, then coerce stabilized values."""
    if not params:
        return list(ir_args)
    if len(ast_args) != len(ir_args):
        _binding_error("internal argument/source association mismatch")

    names = list(arg_names or [])
    names.extend([""] * (len(ast_args) - len(names)))
    param_indices = {param.name: index for index, param in enumerate(params)}
    source_for_slot = [-1] * len(params)
    positional = 0
    for source_index in range(len(ast_args)):
        name = names[source_index]
        if name:
            if name not in param_indices:
                _binding_error(f"unknown named argument '{name}'")
            slot = param_indices[name]
        else:
            slot = positional
            positional += 1
            if slot >= len(params):
                _binding_error("too many positional arguments")
        if source_for_slot[slot] >= 0:
            _binding_error(f"duplicate argument for parameter '{params[slot].name}'")
        source_for_slot[slot] = source_index

    from ..upcast import upcast_class_pointer

    result = []
    for slot, param in enumerate(params):
        source_index = source_for_slot[slot]
        is_default = source_index < 0
        if is_default:
            if param.default is None:
                _binding_error(f"missing required argument for parameter '{param.name}'")
            node = param.default
            value = lower_generic_call_argument(
                emitter,
                param,
                node,
                is_default=True,
            )
        else:
            node = ast_args[source_index]
            value = ir_args[source_index]
        source_type = generic_call_argument_type(
            emitter,
            param,
            node,
            is_default=is_default,
        )
        result.append(
            upcast_class_pointer(
                emitter._gen,
                param.type,
                source_type,
                value,
                emitter._type_renderer,
            )
        )
    return result


def _binding_error(message):
    from ..errors import CodegenError

    raise CodegenError(message)


__all__ = [
    "call_target_substitutions",
    "generic_call_argument_type",
    "in_generic_call_argument_context",
    "lower_generic_call_argument",
    "order_generic_call_arguments",
    "resolved_generic_parameters",
]
