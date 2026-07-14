"""Fail-closed boundaries for untagged managed-return callbacks."""

from __future__ import annotations

from ...ast_nodes import FieldAccessExpr, Identifier, IndexExpr
from .callable_provenance import BORROWED_RETURN, callable_return_abi
from .type_resolution import canonical_type


def managed_callable_type(gen, type_expr) -> bool:
    """Whether a bare function pointer returns an ARC-managed value."""
    from .managed_values import is_managed_type

    resolved = canonical_type(type_expr, gen.analyzed.typedef_table)
    return bool(
        resolved is not None
        and resolved.base == "__fn_ptr"
        and resolved.generic_args
        and is_managed_type(gen, resolved.generic_args[0])
    )


def reject_persistent_callable_escape(gen, expected_type, value, boundary: str) -> None:
    """Reject non-borrowed callbacks where their ABI tag would be lost."""
    if not managed_callable_type(gen, expected_type):
        return
    if callable_return_abi(gen, value) == BORROWED_RETURN:
        return
    from .errors import CodegenError

    raise CodegenError(f"Managed-return callback cannot cross {boundary}; bare __fn_ptr storage erases its return ABI")


def reject_erasing_callable_assignment(gen, assignment) -> None:
    """Reject owned-return callbacks stored outside a lexical local slot."""
    if assignment.op != "=":
        return
    target_type = gen.analyzed.node_types.get(id(assignment.target))
    if not managed_callable_type(gen, target_type):
        return
    target = assignment.target
    if isinstance(target, Identifier) and target.name in gen._callable_return_abis:
        return
    if isinstance(target, Identifier):
        boundary = "global storage"
    elif isinstance(target, FieldAccessExpr):
        boundary = "field storage"
    elif isinstance(target, IndexExpr):
        boundary = "indexed storage"
    else:
        boundary = "persistent storage"
    reject_persistent_callable_escape(gen, target_type, assignment.value, boundary)


def reject_unsafe_managed_callback_arguments(gen, call) -> None:
    """Keep bare callback parameters on the historical borrowed C ABI."""
    from .calls import params_for_call
    from .errors import CodegenError
    from .managed_values import is_managed_type

    params = params_for_call(gen, call)
    if not params:
        return
    positional = 0
    for index, argument in enumerate(call.args):
        argument_name = call.arg_names[index] if index < len(call.arg_names) else None
        if argument_name:
            param_index = next(
                (position for position, param in enumerate(params) if param.name == argument_name),
                -1,
            )
        else:
            param_index = positional
            positional += 1
        if not 0 <= param_index < len(params):
            continue
        actual = canonical_type(
            gen.analyzed.node_types.get(id(argument)),
            gen.analyzed.typedef_table,
        )
        if actual is None or actual.base != "__fn_ptr" or not actual.generic_args:
            continue
        if not is_managed_type(gen, actual.generic_args[0]):
            continue
        if callable_return_abi(gen, argument) == BORROWED_RETURN:
            continue
        parameter = params[param_index]
        raise CodegenError(
            f"Managed-return callback for parameter '{parameter.name}' erases "
            "its source-owned return ABI; bare __fn_ptr parameters accept only "
            "borrowed C callbacks"
        )


__all__ = [
    "managed_callable_type",
    "reject_erasing_callable_assignment",
    "reject_persistent_callable_escape",
    "reject_unsafe_managed_callback_arguments",
]
