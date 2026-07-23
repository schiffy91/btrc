"""Capacity inheritance for declaration-scoped GPU array defaults."""

from .gpu_argument_bindings import default_array_dependency


def lower_default_argument(
    gen,
    host,
    call,
    declaration,
    param_index,
    bound_nodes,
    stable_overrides,
    parameter_values,
    type_renderer,
    default_arguments,
):
    """Evaluate a default with earlier parameters in their kernel ABI form."""

    if call is None:
        from .errors import CodegenError

        raise CodegenError("default GPU argument requires its source call")
    overrides = dict(stable_overrides)
    for index, node in enumerate(bound_nodes[:param_index]):
        if node is not None and index in parameter_values:
            overrides[id(node)] = parameter_values[index]
    from .default_argument_calls import default_call_builder

    return default_call_builder(
        gen,
        call,
        declaration.params,
        param_index,
        bound_nodes,
        type_renderer,
        default_arguments,
        resolve_argument_type=host.resolve_type,
    )(overrides)


def inherited_array_length(
    declaration,
    param_index,
    argument,
    *,
    is_default,
    lengths,
):
    """Reuse the snapshot belonging to a referenced earlier parameter."""

    if not is_default:
        return None
    dependency = default_array_dependency(
        declaration.params,
        param_index,
        argument,
    )
    return lengths.get(dependency) if dependency is not None else None


__all__ = ["inherited_array_length", "lower_default_argument"]
