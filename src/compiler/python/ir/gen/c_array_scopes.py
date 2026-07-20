"""Nearest-binding proof for source names represented as real C arrays."""


def declare_c_binding(gen, name: str, *, is_array: bool) -> None:
    """Record the current scope's representation for one lexical binding."""

    if gen._c_array_scopes:
        gen._c_array_scopes[-1][name] = is_array


def local_c_array_status(gen, name: str) -> bool | None:
    """Return the nearest local binding's array status, or ``None`` if absent."""

    for scope in reversed(gen._c_array_scopes):
        if name in scope:
            return scope[name]
    return None


__all__ = ["declare_c_binding", "local_c_array_status"]
