"""Location-independent keys for semantic AST comparisons."""

from __future__ import annotations

from dataclasses import fields, is_dataclass


def semantic_ast_key(value):
    """Return a recursive key containing only semantically comparable fields.

    Generated AST dataclasses mark source locations with ``compare=False``.
    Honouring that schema metadata explicitly keeps declaration contracts
    independent of where equivalent syntax appeared in the source.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(semantic_ast_key(item) for item in value)
    if not is_dataclass(value):
        raise TypeError(f"unsupported semantic AST value: {type(value).__name__}")
    return (
        type(value).__name__,
        tuple((field.name, semantic_ast_key(getattr(value, field.name))) for field in fields(value) if field.compare),
    )


__all__ = ["semantic_ast_key"]
