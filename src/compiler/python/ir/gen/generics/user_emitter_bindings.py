"""Declaration-specific C identities for generic source bindings."""

from __future__ import annotations


def reset_source_bindings(emitter, parameters=()) -> None:
    """Start one generated function with its source-parameter identities."""
    emitter._local_c_name_scopes = []
    emitter._source_parameter_c_names = {}
    emitter._c_array_scopes = [{parameter.name: False for parameter in parameters}]
    for parameter in parameters:
        bind_source_parameter(emitter, parameter.name)


def bind_source_parameter(emitter, name: str, c_name: str | None = None) -> str:
    """Record the emitted identity of a source-level parameter."""
    c_name = c_name or _base_c_name(emitter, name)
    emitter._source_parameter_c_names[name] = c_name
    emitter._c_array_scopes[0][name] = False
    return c_name


def push_source_binding_scope(emitter) -> None:
    emitter._local_c_name_scopes.append({})
    emitter._c_array_scopes.append({})


def pop_source_binding_scope(emitter) -> None:
    if emitter._local_c_name_scopes:
        emitter._local_c_name_scopes.pop()
        emitter._c_array_scopes.pop()


def declare_source_binding(emitter, name: str, *, c_name: str | None = None) -> str:
    """Activate a local only after its initializer has been lowered."""
    if not emitter._local_c_name_scopes:
        raise RuntimeError("generic source binding requires a lexical scope")
    scope = emitter._local_c_name_scopes[-1]
    if name in scope:
        return scope[name]
    c_name = c_name or next_source_binding_c_name(emitter, name)
    scope[name] = c_name
    emitter._c_array_scopes[-1][name] = False
    return c_name


def next_source_binding_c_name(emitter, name: str) -> str:
    """Allocate a C identity without exposing the new source binding."""
    c_name = _base_c_name(emitter, name)
    active = set(emitter._source_parameter_c_names.values())
    active.update(value for scope in emitter._local_c_name_scopes for value in scope.values())
    return emitter._fresh_temp(c_name) if c_name in active else c_name


def source_binding_c_name(emitter, name: str) -> str:
    """Resolve the innermost declaration-specific C identity."""
    for scope in reversed(emitter._local_c_name_scopes):
        if name in scope:
            return scope[name]
    parameter = emitter._source_parameter_c_names.get(name)
    return parameter if parameter is not None else _base_c_name(emitter, name)


def _base_c_name(emitter, name: str) -> str:
    from ..parameters import source_binding_c_name

    return source_binding_c_name(name, emitter._gen.analyzed)


__all__ = [
    "bind_source_parameter",
    "declare_source_binding",
    "next_source_binding_c_name",
    "pop_source_binding_scope",
    "push_source_binding_scope",
    "reset_source_bindings",
    "source_binding_c_name",
]
