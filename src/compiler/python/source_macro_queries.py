"""Cycle-safe semantic queries over active source macro definitions."""

from __future__ import annotations

from .source_macros import source_macro_replacement_identifiers


def source_macro_expands_to_any(
    name: str,
    definitions,
    identifiers: frozenset[str],
    visiting: frozenset[str] = frozenset(),
) -> bool:
    """Whether an active macro transitively references a target identifier."""
    if name in visiting:
        return False
    directive = definitions.get(name)
    if directive is None:
        return False
    visiting = visiting | {name}
    for identifier in source_macro_replacement_identifiers(directive):
        if identifier in identifiers or source_macro_expands_to_any(
            identifier,
            definitions,
            identifiers,
            visiting,
        ):
            return True
    return False


__all__ = ["source_macro_expands_to_any"]
