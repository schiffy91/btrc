"""Nearest-binding proof for source names represented as real C arrays."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CArrayBinding:
    is_array: bool
    logical_length: object | None = None


def declare_c_binding(
    gen,
    name: str,
    *,
    is_array: bool,
    logical_length=None,
) -> None:
    """Record the current scope's representation for one lexical binding."""

    if gen._c_array_scopes:
        gen._c_array_scopes[-1][name] = (
            CArrayBinding(is_array, logical_length) if logical_length is not None else is_array
        )


def local_c_array_status(gen, name: str) -> bool | None:
    """Return the nearest local binding's array status, or ``None`` if absent."""

    for scope in reversed(gen._c_array_scopes):
        if name in scope:
            binding = scope[name]
            return binding.is_array if isinstance(binding, CArrayBinding) else binding
    return None


def local_gpu_array_length(gen, name: str):
    """Return the logical GPU result length for the nearest binding."""

    for scope in reversed(gen._c_array_scopes):
        if name in scope:
            binding = scope[name]
            return binding.logical_length if isinstance(binding, CArrayBinding) else None
    return None


__all__ = [
    "declare_c_binding",
    "local_c_array_status",
    "local_gpu_array_length",
]
