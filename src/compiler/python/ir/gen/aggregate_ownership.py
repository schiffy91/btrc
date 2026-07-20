"""Fail-closed ownership checks for shallow by-value aggregates."""

from __future__ import annotations

from ...ast_nodes import FieldAccessExpr, IndexExpr
from .errors import CodegenError
from .ownership import owns_result


def reject_owned_elements(gen, elements, aggregate: str) -> None:
    """Reject +1 values that a shallow aggregate cannot later release."""
    for element in elements:
        if owns_result(gen, element):
            raise CodegenError(
                f"caller-owned temporary cannot be embedded in {aggregate}; "
                "aggregate class elements are shallow borrowed references, "
                "so bind the owner to a local first"
            )


def reject_shallow_initializer(gen, node, node_type=None) -> None:
    """Validate a brace/list initializer when its target is non-owning."""
    node_type = node_type or gen.analyzed.node_types.get(id(node))
    canonical = _canonical_type(node_type, gen.analyzed.typedef_table)
    if canonical is None:
        return
    struct_name = canonical.base.removeprefix("struct ")
    shallow = bool(canonical.is_array or canonical.base == "Tuple" or struct_name in gen.analyzed.struct_table)
    if shallow:
        reject_owned_elements(gen, node.elements, "a shallow aggregate")


def reject_rich_enum_owned_args(gen, call) -> None:
    """Reject owned payloads passed into a shallow tagged union variant."""
    from .rich_enum_calls import rich_enum_variant_target

    target = rich_enum_variant_target(gen, call)
    if target is None:
        return
    enum_name, variant = target
    reject_owned_elements(
        gen,
        call.args,
        f"rich-enum payload '{enum_name}.{variant.name}'",
    )
    from .arguments import (
        arg_names_for,
        bind_arg_nodes_to_params,
    )

    bindings = bind_arg_nodes_to_params(
        variant.params,
        call.args,
        arg_names_for(call, len(call.args)),
    )
    for parameter_index, value, is_default in bindings:
        if parameter_index is None or parameter_index >= len(variant.params):
            continue
        parameter = variant.params[parameter_index]
        unsafe = (
            id(value) in gen.analyzed.rich_enum_unsafe_default_ids
            if is_default
            else _payload_value_requires_owner(
                gen,
                parameter,
                value,
            )
        )
        if not unsafe:
            continue
        if is_default:
            raise CodegenError(
                f"Omitted default for rich-enum payload "
                f"'{enum_name}.{variant.name}.{parameter.name}' produces a "
                "caller-owned temporary; rich-enum payloads are shallow "
                "borrowed references, so pass a prebound owner explicitly"
            )
        raise CodegenError(
            f"caller-owned temporary cannot be embedded in rich-enum payload "
            f"'{enum_name}.{variant.name}'; aggregate class elements are shallow "
            "borrowed references, so bind the owner to a local first"
        )


def _payload_value_requires_owner(gen, parameter, value):
    from .default_argument_context import (
        call_argument_type,
        in_call_argument_context,
    )
    from .hosted_result_conversion import requires_target_value_conversion

    source_type = call_argument_type(
        gen,
        parameter,
        value,
        is_default=False,
    )
    return in_call_argument_context(
        parameter,
        False,
        lambda: owns_result(gen, value),
    ) or requires_target_value_conversion(
        gen,
        value,
        parameter.type,
        source_type,
    )


def reject_shallow_store(gen, assignment) -> None:
    """Reject replacing shallow aggregate storage with a +1 temporary."""
    target = assignment.target
    if not isinstance(target, (FieldAccessExpr, IndexExpr)) or not owns_result(
        gen,
        assignment.value,
    ):
        return
    receiver_type = gen.analyzed.node_types.get(id(target.obj))
    if receiver_type is None:
        return
    canonical = _canonical_type(
        receiver_type,
        gen.analyzed.typedef_table,
    )
    if canonical is None:
        return
    struct_name = canonical.base.removeprefix("struct ")
    if canonical.is_array or canonical.base == "Tuple" or struct_name in gen.analyzed.struct_table:
        raise CodegenError(
            "caller-owned temporary cannot be stored in a shallow aggregate; "
            "bind the owner to a local and store only its borrowed reference"
        )


def _canonical_type(type_expr, typedefs):
    from .type_resolution import canonical_type

    return canonical_type(type_expr, typedefs)


__all__ = [
    "reject_owned_elements",
    "reject_rich_enum_owned_args",
    "reject_shallow_initializer",
    "reject_shallow_store",
]
