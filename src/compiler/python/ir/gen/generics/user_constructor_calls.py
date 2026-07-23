"""Class-constructor calls inside generic specializations."""

from ...nodes import IRCall
from .user_call_arguments import (
    order_generic_call_arguments,
    resolved_generic_parameters,
)


def new_constructor_parameters(emitter, expression, class_info, resolved=None):
    resolved = resolved or emitter._resolve(expression.type)
    substitutions = dict(zip(class_info.generic_params, resolved.generic_args))
    return resolved_generic_parameters(
        emitter,
        class_info.constructor.params if class_info.constructor else [],
        substitutions,
    )


def lower_new_constructor_call(emitter, expression):
    resolved = emitter._resolve(expression.type)
    if emitter._gen and resolved.base == "Mutex":
        if len(expression.args) != 1 or not resolved.generic_args:
            from ..errors import CodegenError

            raise CodegenError("Mutex construction requires one initial value")
        from ..mutex_values import create_mutex_value

        return create_mutex_value(
            emitter._gen,
            emitter.lower_expression(expression.args[0]),
            resolved.generic_args[0],
            emitter._type_renderer,
        )

    target = (
        emitter.type_identity.specialization_symbol(resolved.base, resolved.generic_args)
        if resolved.generic_args
        else resolved.base
    )
    args = [emitter.lower_expression(argument) for argument in expression.args]
    class_info = emitter._gen.analyzed.class_table.get(resolved.base) if emitter._gen else None
    if class_info is not None and class_info.constructor:
        params = new_constructor_parameters(
            emitter,
            expression,
            class_info,
            resolved,
        )
        args = order_generic_call_arguments(
            emitter,
            params,
            expression.args,
            getattr(expression, "arg_names", []) or [],
            args,
        )
    return IRCall(callee=f"{target}_new", args=args)


def lower_class_constructor_call(
    emitter,
    expression,
    name,
    args,
    arg_names,
    params,
):
    class_info = emitter._gen.analyzed.class_table.get(name)
    if class_info is None:
        return None
    target = name
    constructor_params = params
    if class_info.generic_params:
        target, resolved_params = emitter._resolved_generic_constructor(
            expression,
            class_info,
        )
        if not constructor_params:
            constructor_params = resolved_params
    if class_info.constructor:
        args = order_generic_call_arguments(
            emitter,
            constructor_params,
            expression.args,
            arg_names,
            args,
        )
    return IRCall(callee=f"{target}_new", args=args)


__all__ = [
    "lower_class_constructor_call",
    "lower_new_constructor_call",
    "new_constructor_parameters",
]
