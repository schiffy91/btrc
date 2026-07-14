"""Shared dataclass-tree and identifier traversal for optimizer passes."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator

IdentifierPattern = re.Pattern[str] | None


def identifier_pattern(names: set[str]) -> IdentifierPattern:
    """Return one whole-identifier regex for ``names`` or ``None`` when empty."""
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=lambda item: (-len(item), item)))
    return re.compile(rf"\b(?:{alternatives})\b")


def scan_text(text: str, pattern: IdentifierPattern, out: set[str]) -> None:
    """Add every identifier matched in ``text`` to ``out``."""
    if pattern is not None:
        out.update(pattern.findall(text))


def scan_macro_replacements(macros, pattern: IdentifierPattern, out: set[str]) -> None:
    """Scan only macro replacement tokens, not declaration names or params."""

    for declaration in macros:
        replacement = getattr(declaration, "replacement", None)
        if isinstance(replacement, str):
            scan_text(replacement, pattern, out)


def collect_c_type_references(
    value: object,
    pattern: IdentifierPattern,
    out: set[str],
) -> None:
    """Collect identifiers only from resolved :class:`CType` leaves.

    Declaration names, variable names, source paths, and literal payload text
    are not type references. Runtime-helper source and macro replacements are
    separate explicit text boundaries handled by their callers.
    """

    from .expr_nodes import CType

    for node in iter_ir_nodes(value):
        if isinstance(node, CType):
            scan_text(node.text, pattern, out)


def collect_value_references(
    value: object,
    names: set[str],
    out: set[str],
) -> None:
    """Collect exact structured value references, excluding literal payloads."""

    from .expr_nodes import IRVar

    for node in iter_ir_nodes(value):
        if isinstance(node, IRVar) and node.name in names:
            out.add(node.name)


def collect_callable_references(
    value: object,
    names: set[str],
    out: set[str],
) -> None:
    """Collect direct calls and address-taken callable values by exact name."""

    from .expr_nodes import IRCall, IRVar

    for node in iter_ir_nodes(value):
        if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in names:
            out.add(node.callee)
        elif isinstance(node, IRVar) and node.name in names:
            out.add(node.name)


def iter_ir_nodes(value: object) -> Iterator[object]:
    """Yield every dataclass node in an acyclic IR-shaped value."""
    if dataclasses.is_dataclass(value):
        yield value
        for field in dataclasses.fields(value):
            yield from iter_ir_nodes(getattr(value, field.name))
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_ir_nodes(item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from iter_ir_nodes(item)
