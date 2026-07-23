"""Source bindings and lifetime facts for GPU arguments."""


def argument_c_type(parameter_type, argument_type, render_type) -> str:
    effective = argument_type or parameter_type
    return render_type(effective) if effective is not None else "int"


def buffer_length_name(parameter_name: str) -> str:
    return f"__gpu_len_{parameter_name}"


def plan_gpu_argument_bindings(gen, host, declaration, ast_args, arg_names):
    from .arguments import bind_arg_nodes_to_params
    from .default_argument_calls import bound_nodes_by_parameter
    from .errors import CodegenError
    from .evaluation_order import source_order_pin_flags

    bindings = []
    seen = set()
    for slot, argument, is_default in bind_arg_nodes_to_params(
        declaration.params,
        ast_args,
        arg_names,
    ):
        if slot is None or slot >= len(declaration.params):
            raise CodegenError(f"@gpu call '{declaration.name}' contains an unknown argument")
        if slot in seen:
            raise CodegenError(f"duplicate @gpu argument for parameter '{declaration.params[slot].name}'")
        seen.add(slot)
        bindings.append((slot, argument, is_default))
    types = [host.resolve_type(argument) or declaration.params[index].type for index, argument, _is_default in bindings]
    owned = [
        bool(_heap_collection(type_expr) and host.owns_result(argument))
        for (_index, argument, _is_default), type_expr in zip(
            bindings,
            types,
        )
    ]
    pins = source_order_pin_flags(
        gen,
        [argument for _index, argument, _is_default in bindings],
        types,
        owned,
        type_of=host.resolve_type,
        is_managed=host.is_managed,
    )
    return (
        bindings,
        bound_nodes_by_parameter(declaration.params, bindings),
        types,
        owned,
        pins,
    )


def _heap_collection(type_expr) -> bool:
    return bool(
        type_expr is not None and getattr(type_expr, "generic_args", None) and type_expr.base in ("Array", "Vector")
    )


def default_array_dependency(params, param_index, argument):
    """Find an earlier array parameter referenced by a simple default."""

    from ...ast_nodes import Identifier

    if not isinstance(argument, Identifier):
        return None
    for index, parameter in enumerate(params[:param_index]):
        if parameter.name == argument.name and parameter.type is not None and parameter.type.is_array:
            return index
    return None


__all__ = [
    "argument_c_type",
    "buffer_length_name",
    "default_array_dependency",
    "plan_gpu_argument_bindings",
]
