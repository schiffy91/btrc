"""Owned dataclass-tree and identifier traversal for IR passes."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator

IdentifierPattern = re.Pattern[str] | None


class IdentifierReferences:
    """Whole-identifier vocabulary used at explicit textual IR boundaries."""

    def __init__(self, names: Iterable[str]):
        self._names = frozenset(names)
        alternatives = "|".join(re.escape(name) for name in sorted(self._names, key=lambda item: (-len(item), item)))
        self._pattern: IdentifierPattern = re.compile(rf"\b(?:{alternatives})\b") if alternatives else None

    def scan(self, text: str, out: set[str]) -> None:
        """Add every vocabulary member matched in ``text`` to ``out``."""
        if self._pattern is not None:
            out.update(self._pattern.findall(text))

    def scan_macro_replacements(self, macros, out: set[str]) -> None:
        """Scan macro replacement tokens, excluding names and parameters."""
        for declaration in macros:
            replacement = getattr(declaration, "replacement", None)
            if isinstance(replacement, str):
                self.scan(replacement, out)


class IRTree:
    """One acyclic IR-shaped value and the typed queries over its nodes."""

    def __init__(self, root: object):
        self._root = root

    def __iter__(self) -> Iterator[object]:
        yield from self._walk(self._root)

    def collect_c_type_references(
        self,
        identifiers: IdentifierReferences,
        out: set[str],
    ) -> None:
        """Collect identifiers only from resolved :class:`CType` leaves."""
        from .expr_nodes import CType

        for node in self:
            if isinstance(node, CType):
                identifiers.scan(node.text, out)

    def collect_value_references(self, names: set[str], out: set[str]) -> None:
        """Collect exact structured value references, excluding literals."""
        from .expr_nodes import IRVar

        for node in self:
            if isinstance(node, IRVar) and node.name in names:
                out.add(node.name)

    def collect_callable_references(self, names: set[str], out: set[str]) -> None:
        """Collect direct calls and address-taken callables by exact name."""
        from .expr_nodes import IRCall, IRFunctionRef

        for node in self:
            if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in names:
                out.add(node.callee)
            elif isinstance(node, IRFunctionRef) and node.name in names:
                out.add(node.name)

    @classmethod
    def _walk(cls, value: object) -> Iterator[object]:
        if dataclasses.is_dataclass(value):
            yield value
            for field in dataclasses.fields(value):
                yield from cls._walk(getattr(value, field.name))
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from cls._walk(item)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from cls._walk(item)


__all__ = ["IRTree", "IdentifierReferences"]
