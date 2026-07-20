"""IR invariants for typed exception-cleanup slot registrations."""

from __future__ import annotations

import dataclasses

from .nodes import (
    IRAddressOf,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRFunctionRef,
    IRVar,
    IRVarDecl,
)

_REGISTER_ARITY = {
    "__btrc_register_cleanup": 4,
    "__btrc_register_direct_cleanup": 3,
}


def validate_cleanup_slots(module) -> None:
    """Reject legacy aliasing casts or incomplete cleanup-slot metadata."""

    functions = {function.name: function for function in module.function_defs}
    attached_sites: dict[int, str] = {}
    for function in module.function_defs:
        declarations: dict[int, IRCleanupSlot] = {}
        registrations: list[IRCall] = []
        for node in _walk(function.body):
            if isinstance(node, IRVarDecl) and node.cleanup_slot is not None:
                metadata = node.cleanup_slot
                _validate_declaration(node, metadata)
                site = id(metadata)
                if site in attached_sites:
                    raise ValueError(f"cleanup metadata for {metadata.name!r} is attached more than once")
                attached_sites[site] = function.name
                declarations[site] = metadata
            if isinstance(node, IRCall):
                if isinstance(node.callee, str) and node.callee in _REGISTER_ARITY:
                    registrations.append(node)
                elif node.cleanup_slot is not None:
                    raise ValueError("cleanup metadata is attached to a non-registration call")
        _validate_function_registrations(
            function.name,
            declarations,
            registrations,
            functions,
        )


def _validate_declaration(declaration: IRVarDecl, metadata: IRCleanupSlot) -> None:
    if metadata.name != declaration.name or metadata.c_type != declaration.c_type:
        raise ValueError(f"cleanup metadata does not describe slot {declaration.name!r}")
    if not declaration.is_volatile:
        raise ValueError(f"cleanup slot {declaration.name!r} is not volatile")


def _validate_function_registrations(
    function_name,
    declarations,
    registrations,
    functions,
) -> None:
    used_slots: set[int] = set()
    for call in registrations:
        metadata = _validate_registration(call)
        if id(metadata) not in declarations:
            raise ValueError(
                f"cleanup registration for {metadata.name!r} has no typed declaration in function {function_name!r}"
            )
        adapter = functions.get(metadata.take_function)
        if adapter is None or not adapter.is_static:
            raise ValueError(f"cleanup take adapter {metadata.take_function!r} is missing or non-static")
        used_slots.add(id(metadata))

    unused = declarations.keys() - used_slots
    if unused:
        names = ", ".join(sorted(declarations[site].name for site in unused))
        raise ValueError(f"cleanup slot metadata has no registration: {names}")


def _validate_registration(call: IRCall) -> IRCleanupSlot:
    expected_arity = _REGISTER_ARITY[call.callee]
    if call.helper_ref != call.callee or len(call.args) != expected_arity:
        raise ValueError(f"malformed {call.callee} call")
    metadata = call.cleanup_slot
    if metadata is None:
        raise ValueError(f"legacy untyped {call.callee} call")

    address = call.args[0]
    if (
        not isinstance(address, IRCast)
        or address.target_type.text != "void*"
        or not isinstance(address.expr, IRAddressOf)
        or not isinstance(address.expr.expr, IRVar)
        or address.expr.expr.name != metadata.name
    ):
        raise ValueError(f"cleanup slot {metadata.name!r} must use an opaque void* address")
    take = call.args[1]
    if not isinstance(take, IRFunctionRef) or take.name != metadata.take_function:
        raise ValueError(f"cleanup slot {metadata.name!r} has the wrong take adapter")
    return metadata


def _walk(value):
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _walk(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
        return
    yield value
    if dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from _walk(getattr(value, field.name))


__all__ = ["validate_cleanup_slots"]
