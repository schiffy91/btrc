"""Compiler-prefixed runtime symbols intentionally callable from source."""

from .hosted_abi import SOURCE_RUNTIME_HELPERS
from .operator_semantics import GENERIC_INTRINSICS


def is_source_runtime_helper(name: str) -> bool:
    return name in SOURCE_RUNTIME_HELPERS


def is_source_runtime_intrinsic(name: str) -> bool:
    """Whether ``name`` is supported specifically as a direct source call."""
    return is_source_runtime_helper(name) or name in GENERIC_INTRINSICS


def is_compiler_owned_symbol(name: str) -> bool:
    """Whether an unresolved spelling belongs to a btrc-owned namespace.

    C reserves every double-underscore declaration, but preprocessing
    replacements legitimately reference standard predefined macros such as
    ``__FILE__``, ``__LINE__``, and ``__VA_ARGS__``.  Declaration validation
    enforces the broader C rule; unresolved reference validation owns only the
    namespaces the compiler can actually synthesize.
    """
    return name.startswith(("__btrc_", "__BTRC_", "__gpu_", "btrc_"))


__all__ = [
    "SOURCE_RUNTIME_HELPERS",
    "is_compiler_owned_symbol",
    "is_source_runtime_helper",
    "is_source_runtime_intrinsic",
]
