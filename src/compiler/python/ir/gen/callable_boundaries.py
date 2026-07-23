"""Fail-closed boundaries for untagged managed-return callbacks."""

from __future__ import annotations

from ...ast_nodes import (
    BraceInitializer,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    ListLiteral,
    MapLiteral,
    TupleLiteral,
)
from .callable_provenance import BORROWED_RETURN, callable_return_abi
from .type_resolution import canonical_type


def managed_callable_type(gen, type_expr) -> bool:
    """Whether a bare function pointer returns an ARC-managed value."""

    resolved = canonical_type(type_expr, gen.analyzed.typedef_table)
    return bool(
        resolved is not None
        and resolved.base == "__fn_ptr"
        and resolved.pointer_depth == 0
        and not resolved.is_array
        and resolved.generic_args
        and gen.managed_values.is_managed(resolved.generic_args[0])
    )


def reject_persistent_callable_escape(
    gen,
    expected_type,
    value,
    boundary: str,
    *,
    callable_abi=None,
) -> None:
    """Reject non-borrowed callbacks where their ABI tag would be lost.

    Aggregate literals are traversed against their contextual storage type:
    every nested callback slot is ABI-erasing just like a direct field.
    """
    callable_abi = callable_abi or (lambda expression: callable_return_abi(gen.context, expression))
    if not _contains_unsafe_managed_callback(
        gen,
        expected_type,
        value,
        callable_abi,
    ):
        return
    from .errors import CodegenError

    raise CodegenError(f"Managed-return callback cannot cross {boundary}; bare __fn_ptr storage erases its return ABI")


def reject_erasing_callable_assignment(
    gen,
    assignment,
    *,
    type_of=None,
    callable_abi=None,
    identifier_is_callable_local=None,
    identifier_is_local=None,
) -> None:
    """Reject owned-return callbacks stored outside a lexical local slot."""
    if assignment.op != "=":
        return
    type_of = type_of or (lambda expression: gen.analyzed.node_types.get(id(expression)))
    identifier_is_callable_local = identifier_is_callable_local or (
        lambda name: name in gen.context.callable_return_abis
    )
    identifier_is_local = identifier_is_local or gen.local_ownership_declared
    target_type = type_of(assignment.target)
    target = assignment.target
    if (
        isinstance(target, Identifier)
        and managed_callable_type(gen, target_type)
        and identifier_is_callable_local(target.name)
    ):
        return
    if isinstance(target, Identifier):
        boundary = "aggregate storage" if identifier_is_local(target.name) else "global storage"
    elif isinstance(target, FieldAccessExpr):
        boundary = "field storage"
    elif isinstance(target, IndexExpr):
        boundary = "indexed storage"
    else:
        boundary = "persistent storage"
    reject_persistent_callable_escape(
        gen,
        target_type,
        assignment.value,
        boundary,
        callable_abi=callable_abi,
    )


def reject_aggregate_callable_initializer(
    gen,
    expected_type,
    value,
    *,
    callable_abi=None,
) -> None:
    """Reject ABI-erasing callback slots inside a lexical aggregate local."""
    if managed_callable_type(gen, expected_type):
        return
    reject_persistent_callable_escape(
        gen,
        expected_type,
        value,
        "aggregate storage",
        callable_abi=callable_abi,
    )


def reject_unsafe_managed_callback_arguments(
    gen,
    call,
    *,
    params=None,
    callable_abi=None,
) -> None:
    """Keep bare callback parameters on the historical borrowed C ABI."""
    from .arguments import bind_arg_nodes_to_params
    from .errors import CodegenError

    if params is None:
        params = gen.calls.resolver.resolved_params(call)
    if not params:
        return
    callable_abi = callable_abi or (lambda expression: callable_return_abi(gen.context, expression))
    for param_index, argument, _is_default in bind_arg_nodes_to_params(
        params,
        call.args,
        getattr(call, "arg_names", ()) or (),
    ):
        if param_index is None or not 0 <= param_index < len(params):
            continue
        parameter = params[param_index]
        if not _contains_unsafe_managed_callback(
            gen,
            parameter.type,
            argument,
            callable_abi,
        ):
            continue
        raise CodegenError(
            f"Managed-return callback for parameter '{parameter.name}' erases "
            "its source-owned return ABI; bare __fn_ptr parameters accept only "
            "borrowed C callbacks"
        )


def _contains_unsafe_managed_callback(
    gen,
    expected_type,
    value,
    callable_abi,
) -> bool:
    if expected_type is None or value is None:
        return False
    expected = canonical_type(expected_type, gen.analyzed.typedef_table)
    if expected is None:
        return False
    if managed_callable_type(gen, expected):
        return callable_abi(value) != BORROWED_RETURN

    slots = _literal_aggregate_slots(gen, expected, value)
    if slots is not None:
        return any(
            _contains_unsafe_managed_callback(
                gen,
                slot_type,
                element,
                callable_abi,
            )
            for slot_type, element in slots
        )
    if _is_validated_reference_owner(gen, expected):
        return False
    # By-value aggregate values carry no runtime ownership tag for callback
    # leaves. Only a contextual literal lets us prove every stored callback is
    # on the borrowed C ABI; identifiers/calls must therefore fail closed.
    return _type_contains_managed_callback(gen, expected)


def _is_validated_reference_owner(gen, expected_type) -> bool:
    """Whether storage behind this reference enforces callback boundaries."""
    expected = canonical_type(expected_type, gen.analyzed.typedef_table)
    return bool(expected is not None and (expected.pointer_depth > 0 or expected.base in gen.analyzed.class_table))


def _type_contains_managed_callback(
    gen,
    expected_type,
    seen: frozenset[tuple] = frozenset(),
) -> bool:
    """Whether one by-value aggregate recursively contains a managed callback."""
    expected = canonical_type(expected_type, gen.analyzed.typedef_table)
    if expected is None:
        return False
    if managed_callable_type(gen, expected):
        return True
    if _is_validated_reference_owner(gen, expected):
        return False
    key = gen.type_identity.shape_key(expected)
    if key in seen:
        return False
    seen = seen | {key}
    if expected.is_array:
        from ...type_composition import strip_outer_storage

        element_type = strip_outer_storage(expected, array=True)
        return _type_contains_managed_callback(gen, element_type, seen)
    if expected.pointer_depth > 0:
        return False
    if expected.base in {"Array", "List", "Set", "Vector"}:
        return bool(
            len(expected.generic_args) == 1
            and _type_contains_managed_callback(
                gen,
                expected.generic_args[0],
                seen,
            )
        )
    if expected.base in {"Map", "Tuple"}:
        return any(_type_contains_managed_callback(gen, argument, seen) for argument in expected.generic_args)
    declaration = _struct_declaration(gen, expected)
    return bool(
        declaration is not None
        and any(_type_contains_managed_callback(gen, field.type, seen) for field in declaration.fields)
    )


def _literal_aggregate_slots(gen, expected, value):
    if isinstance(value, (BraceInitializer, ListLiteral)):
        return _positional_aggregate_slots(gen, expected, value)
    if isinstance(value, TupleLiteral) and expected.base == "Tuple":
        return zip(expected.generic_args, value.elements)
    if isinstance(value, MapLiteral) and expected.base == "Map" and len(expected.generic_args) == 2:
        key_type, value_type = expected.generic_args
        return (slot for entry in value.entries for slot in ((key_type, entry.key), (value_type, entry.value)))
    return None


def _positional_aggregate_slots(gen, expected, value):
    if expected.is_array:
        from ...type_composition import strip_outer_storage

        element_type = strip_outer_storage(expected, array=True)
        return ((element_type, element) for element in value.elements)
    if expected.base in {"Array", "List", "Set", "Vector"} and len(expected.generic_args) == 1:
        return ((expected.generic_args[0], element) for element in value.elements)
    if expected.base == "Tuple":
        return zip(expected.generic_args, value.elements)
    declaration = _struct_declaration(gen, expected)
    if declaration is not None and not declaration.is_forward:
        return zip((field.type for field in declaration.fields), value.elements)
    return None


def _struct_declaration(gen, expected):
    if expected.pointer_depth > 0:
        return None
    struct_name = expected.base.removeprefix("struct ")
    declaration = gen.analyzed.struct_table.get(struct_name)
    if declaration is None or declaration.is_forward:
        return None
    return declaration


__all__ = [
    "managed_callable_type",
    "reject_aggregate_callable_initializer",
    "reject_erasing_callable_assignment",
    "reject_persistent_callable_escape",
    "reject_unsafe_managed_callback_arguments",
]
