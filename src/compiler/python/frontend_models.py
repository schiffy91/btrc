"""Data contracts for resolved, parsed, and analyzed front-end state."""

import hashlib
import os
from dataclasses import dataclass, field
from functools import cached_property

from .analyzer.core import AnalyzedProgram
from .ast_nodes import Program
from .tokens import Token


@dataclass
class FrontendSource:
    """Resolved source bundle passed from include/stdlib resolution into parsing."""

    user_source: str
    source: str
    stdlib_source: str = ""
    provenance: list[str] = field(default_factory=list)
    source_positions: list[tuple[str, int]] = field(default_factory=list)
    graph: dict[str, set[str]] = field(default_factory=dict)
    strict_imports: bool = False
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

        add_text("btrc-source-provenance-v1")
        add_text(self.root_source_path)
        for source_file, native_line in self.source_positions:
            normalized = os.path.abspath(source_file) if os.path.exists(source_file) else source_file
            add_text(normalized)
            digest.update(int(native_line).to_bytes(8, "big", signed=True))
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
    graph: dict[str, set[str]] = field(default_factory=dict)


class FrontendVisibilityError(Exception):
    """Strict-import visibility failures."""

    def __init__(self, errors: list[tuple[str, int, int]]):
        self.errors = errors
        super().__init__("strict import visibility failed")
