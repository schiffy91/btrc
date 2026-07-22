"""Typed abstract locations used by setjmp pointer-effect analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from .setjmp_pointer_types import OPAQUE_POINTER_DEPTH


@dataclass(frozen=True)
class Storage:
    """One lexically resolved C object with exact or opaque pointer depth."""

    name: str
    identity: int
    kind: str
    pointer_depth: int = 0
    is_array: bool = False
    compiler_owned: bool = False

    @property
    def is_pointer(self) -> bool:
        return self.pointer_depth != 0

    @property
    def automatic(self) -> bool:
        return self.kind in {"automatic", "parameter"}


@dataclass(frozen=True)
class PointerOrigin:
    """A concrete object or relative pointee; negative depth is saturated."""

    storage: Storage
    depth: int = 0
    source_exposed: bool = False

    def deeper(self) -> PointerOrigin:
        if self.depth < 0 or self.storage.pointer_depth < 0:
            return self.saturated()
        return PointerOrigin(
            self.storage,
            self.depth + 1,
            self.source_exposed,
        )

    def saturated(self) -> PointerOrigin:
        return PointerOrigin(
            self.storage,
            OPAQUE_POINTER_DEPTH,
            self.source_exposed,
        )


@dataclass(frozen=True, order=True)
class ParameterEffect:
    index: int
    depth: int = 1


@dataclass(frozen=True)
class FunctionEffect:
    writes: frozenset[ParameterEffect] = frozenset()
    captures: frozenset[ParameterEffect] = frozenset()
    returns: frozenset[ParameterEffect] = frozenset()
    unknown_return: bool = False


@dataclass
class PointerFlowResult:
    writes: dict[int, set[PointerOrigin]] = field(default_factory=dict)
    origins: dict[int, set[PointerOrigin]] = field(default_factory=dict)
    storages: dict[int, Storage] = field(default_factory=dict)
    captures: set[PointerOrigin] = field(default_factory=set)
    returns: set[PointerOrigin] = field(default_factory=set)
    unknown_pointer_values: set[Storage] = field(default_factory=set)

    def record_origins(self, value: object, origins) -> set[PointerOrigin]:
        result = set(origins)
        self.origins.setdefault(id(value), set()).update(result)
        return result

    def record_write(self, value: object, origins) -> None:
        self.writes.setdefault(id(value), set()).update(origins)


__all__ = [
    "FunctionEffect",
    "ParameterEffect",
    "PointerFlowResult",
    "PointerOrigin",
    "Storage",
]
