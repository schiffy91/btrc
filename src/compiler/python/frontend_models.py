"""Data contracts for resolved, parsed, and analyzed front-end state."""

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property

from .analyzer.core import AnalyzedProgram
from .ast_nodes import Program
from .tokens import Token


class SourceDependencyKind(Enum):
    """The source-composition relationship represented by a graph edge."""

    IMPORT = "import"
    INCLUDE = "include"


@dataclass(frozen=True)
class SourceDependency:
    """One typed outgoing dependency from a source file."""

    target: str
    kind: SourceDependencyKind


@dataclass
class SourceDependencyGraph:
    """Typed source graph with language visibility semantics.

    ``import`` is directed. Legacy btrc ``#include`` composes both files into
    one compilation unit, so visibility traversal treats include edges as
    reciprocal while retaining their distinct edge kind here.
    """

    _outgoing: dict[str, set[SourceDependency]] = field(default_factory=dict)

    @staticmethod
    def canonical_file(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    def ensure_source(self, source: str) -> None:
        self._outgoing.setdefault(os.path.abspath(source), set())

    def add(self, source: str, target: str, kind: SourceDependencyKind) -> None:
        source = os.path.abspath(source)
        target = os.path.abspath(target)
        self.ensure_source(source)
        self.ensure_source(target)
        self._outgoing[source].add(SourceDependency(target, kind))

    def add_import(self, source: str, target: str) -> None:
        self.add(source, target, SourceDependencyKind.IMPORT)

    def add_include(self, source: str, target: str) -> None:
        self.add(source, target, SourceDependencyKind.INCLUDE)

    def dependencies_from(self, source: str) -> frozenset[SourceDependency]:
        return frozenset(self._outgoing.get(os.path.abspath(source), ()))

    def iter_edges(self) -> Iterator[tuple[str, SourceDependency]]:
        for source, dependencies in self._outgoing.items():
            for dependency in dependencies:
                yield source, dependency

    def has_target(self, target: str) -> bool:
        canonical_target = self.canonical_file(target)
        return any(self.canonical_file(dependency.target) == canonical_target for _, dependency in self.iter_edges())

    def cache_records(self) -> tuple[tuple[str, str, str], ...]:
        """Canonical, deterministic edge records for artifact identities."""

        return tuple(
            sorted(
                (
                    self.canonical_file(source),
                    dependency.kind.value,
                    self.canonical_file(dependency.target),
                )
                for source, dependency in self.iter_edges()
            )
        )

    def visibility_reachable(self, start: str) -> set[str]:
        """Return files visible from ``start`` under import/include rules."""

        adjacency: dict[str, set[str]] = {}
        for source, dependency in self.iter_edges():
            canonical_source = self.canonical_file(source)
            canonical_target = self.canonical_file(dependency.target)
            adjacency.setdefault(canonical_source, set()).add(canonical_target)
            adjacency.setdefault(canonical_target, set())
            if dependency.kind is SourceDependencyKind.INCLUDE:
                adjacency[canonical_target].add(canonical_source)

        canonical_start = self.canonical_file(start)
        seen = {canonical_start}
        pending = list(adjacency.get(canonical_start, ()))
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            pending.extend(adjacency.get(path, ()) - seen)
        return seen


@dataclass
class FrontendSource:
    """Resolved source bundle passed from include/stdlib resolution into parsing."""

    user_source: str
    source: str
    stdlib_source: str = ""
    provenance: list[str] = field(default_factory=list)
    source_positions: list[tuple[str, int]] = field(default_factory=list)
    graph: SourceDependencyGraph = field(default_factory=SourceDependencyGraph)
    strict_imports: bool = True
    root_source_path: str = ""

    @cached_property
    def _user_position_offset(self) -> int:
        """Index in ``source_positions`` where user-source line entries begin."""
        return len(self.source_positions) - (self.user_source.count("\n") + 1)

    def map_line(self, line: int, space: str = "combined") -> tuple[str, int] | None:
        """Translate a 1-based parse-space line to ``(source_file, native_line)``.

        ``space`` is "combined" (stdlib + user concatenation), "user" (resolved
        user source), or "stdlib" (composed stdlib source). Returns None when
        unmappable (out of range, or stdlib positions were not requested).
        """
        offset = self._user_position_offset
        if space == "combined":
            stdlib_lines = self.stdlib_source.count("\n") + 1 if self.stdlib_source else 0
            if line > stdlib_lines:
                space, line = "user", line - stdlib_lines
            else:
                space = "stdlib"
        if space == "stdlib":
            idx, lo, hi = line - 1, 0, offset
        else:
            idx, lo, hi = offset + line - 1, offset, len(self.source_positions)
        if line >= 1 and lo <= idx < hi:
            return self.source_positions[idx]
        return None

    def map_diag_line(
        self, line: int, *, diag_file: str | None = None, split_spaces: bool = False
    ) -> tuple[str, int] | None:
        """Resolve a diagnostic position to ``(source_file, native_line)``.

        ``split_spaces`` means stdlib and user code were parsed separately
        (stdlib AST cache), so each position is native to whichever space
        produced it; ``diag_file`` (decl ``source_file`` provenance) selects
        the stdlib space when it names a stdlib-composed file.
        """
        if not split_spaces:
            return self.map_line(line, "combined")
        offset = self._user_position_offset
        if diag_file is not None and any(f == diag_file for f, _ in self.source_positions[:offset]):
            return self.map_line(line, "stdlib")
        return self.map_line(line, "user")

    def map_declaration_line(
        self,
        line: int,
        source_file: str | None,
        *,
        split_spaces: bool,
    ) -> tuple[str, int] | None:
        """Map a declaration line from combined or split parse coordinates."""

        if not split_spaces:
            return self.map_line(line, "combined")
        if not source_file:
            return None
        expected = os.path.normcase(os.path.realpath(source_file))
        for space in ("user", "stdlib"):
            mapped = self.map_line(line, space)
            if mapped is not None and os.path.normcase(os.path.realpath(mapped[0])) == expected:
                return mapped
        return None

    def cache_identity(self) -> str:
        """Hash source paths and native lines that can shape generated C.

        Resolved text alone is insufficient because declaration-scoped
        ``__FILE__`` and ``__LINE__`` defaults are frozen from this mapping.
        Length framing keeps arbitrary filesystem names unambiguous.
        """

        digest = hashlib.sha256()

        def add_text(value: str) -> None:
            encoded = value.encode("utf-8", errors="surrogatepass")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)

        add_text("btrc-source-provenance-v2")
        add_text(self.root_source_path)
        for source_file, native_line in self.source_positions:
            normalized = os.path.abspath(source_file) if os.path.exists(source_file) else source_file
            add_text(normalized)
            digest.update(int(native_line).to_bytes(8, "big", signed=True))
        for source, kind, target in self.graph.cache_records():
            add_text(source)
            add_text(kind)
            add_text(target)
        return digest.hexdigest()


@dataclass
class StdlibSource:
    source: str
    source_positions: list[tuple[str, int]]


@dataclass
class FrontendParseResult:
    """Lexer/parser output. ``program`` is absent for token-only requests."""

    tokens: list[Token]
    program: Program | None = None
    user_program: Program | None = None


@dataclass
class FrontendResult:
    """Successful front-end compilation result."""

    source: str
    user_source: str
    stdlib_source: str
    tokens: list[Token]
    program: Program
    analyzed: AnalyzedProgram
    source_bundle: FrontendSource
    user_program: Program | None = None
    provenance: list[str] = field(default_factory=list)
    source_positions: list[tuple[str, int]] = field(default_factory=list)
    graph: SourceDependencyGraph = field(default_factory=SourceDependencyGraph)


class FrontendVisibilityError(Exception):
    """Strict-import visibility failures."""

    def __init__(self, errors: list[tuple[str, int, int]]):
        self.errors = errors
        super().__init__("strict import visibility failed")
