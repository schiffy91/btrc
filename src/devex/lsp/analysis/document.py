"""Immutable document snapshots and the compiler-backed analysis owner."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.request import url2pathname

from lsprotocol import types as lsp

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.frontend.imports import ImportVisibilityChecker, ImportVisibilityFailure
from src.compiler.python.frontend.sources import SourceDependencyGraph
from src.compiler.python.syntax.ast.generated import Program
from src.compiler.python.syntax.tokens import Token
from src.devex.lsp.workspace.units import FileUnit
from src.devex.lsp.workspace.workspace import Workspace


@dataclass(frozen=True)
class DocumentText:
    """One source buffer with explicit compiler/LSP coordinate conversion."""

    source: str

    def line(self, line: int) -> str:
        lines = self.source.split("\n")
        if not 0 <= line < len(lines):
            return ""
        return lines[line][:-1] if lines[line].endswith("\r") else lines[line]

    @staticmethod
    def utf16_length(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    @classmethod
    def codepoint_to_utf16(cls, text: str, offset: int) -> int:
        offset = min(max(0, offset), len(text))
        return cls.utf16_length(text[:offset])

    @staticmethod
    def utf16_to_codepoint(text: str, offset: int) -> int:
        """Map a UTF-16 offset to a code-point boundary, clamping invalid input."""

        if offset <= 0:
            return 0
        units = 0
        for index, char in enumerate(text):
            width = 2 if ord(char) > 0xFFFF else 1
            if units + width > offset:
                return index
            units += width
            if units == offset:
                return index + 1
        return len(text)

    def source_position(self, position: lsp.Position) -> lsp.Position:
        """Convert a client UTF-16 position to an internal code-point position."""

        line = min(max(0, position.line), max(0, self.source.count("\n")))
        character = self.utf16_to_codepoint(self.line(line), position.character)
        return lsp.Position(line=line, character=character)

    def protocol_position(self, line: int, col: int) -> lsp.Position:
        """Convert a 1-based compiler position to a 0-based LSP position."""

        line0 = max(0, line - 1)
        character = self.codepoint_to_utf16(self.line(line0), max(0, col - 1))
        return lsp.Position(line=line0, character=character)

    def protocol_range(self, line: int, col: int, length: int = 0) -> lsp.Range:
        """Return an LSP range for a single-line compiler span."""

        start = self.protocol_position(line, col)
        end_codepoint = max(0, col - 1) + max(0, length)
        end = lsp.Position(
            line=start.line,
            character=self.codepoint_to_utf16(self.line(start.line), end_codepoint),
        )
        return lsp.Range(start=start, end=end)

    def before(self, position: lsp.Position) -> str:
        position = self.source_position(position)
        lines = self.source.split("\n")
        if not lines:
            return ""
        line = min(position.line, len(lines) - 1)
        return "\n".join([*lines[:line], lines[line][: position.character]])


@dataclass
class DocumentAnalysis:
    """One compiler snapshot, including its provenance and lazy feature indexes."""

    uri: str
    source: str
    diagnostics: list[lsp.Diagnostic] = field(default_factory=list)
    tokens: list[Token] | None = None
    ast: Program | None = None
    analyzed: AnalyzedProgram | None = None
    source_positions: list[tuple[str, int]] = field(default_factory=list)
    path: str = ""
    units: list[FileUnit] = field(default_factory=list)
    graph: SourceDependencyGraph = field(default_factory=SourceDependencyGraph)
    visibility_failures: tuple[ImportVisibilityFailure, ...] = ()
    snapshot_source: str | None = field(default=None, repr=False)
    _caches: dict = field(default_factory=dict, repr=False)

    @property
    def text(self) -> DocumentText:
        return DocumentText(self.source)

    def line_changed_since_snapshot(self, line: int) -> bool:
        if self.snapshot_source is None:
            return False
        return self.text.line(line) != DocumentText(self.snapshot_source).line(line)

    def is_current(self) -> bool:
        return self.snapshot_source is None

    def positions_are_stable(self) -> bool:
        return self.snapshot_source is None or self.source.startswith(self.snapshot_source)

    def is_current_at(self, line: int) -> bool:
        return self.positions_are_stable() or not self.line_changed_since_snapshot(line)

    def with_live_source(self, source: str) -> DocumentAnalysis:
        if source == self.source:
            return self
        return DocumentAnalysis(
            uri=self.uri,
            source=source,
            diagnostics=self.diagnostics,
            tokens=self.tokens,
            ast=self.ast,
            analyzed=self.analyzed,
            source_positions=self.source_positions,
            path=self.path,
            units=self.units,
            graph=self.graph,
            visibility_failures=self.visibility_failures,
            snapshot_source=self.source,
            _caches=self._caches,
        )


class DocumentAnalyzer:
    """Own compiler-backed document analysis for one retained workspace."""

    _WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:(?:[/\\]|$)")

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    @classmethod
    def path_from_uri(cls, uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme and parsed.scheme != "file":
            suffix = os.path.splitext(parsed.path)[1] or ".btrc"
            digest = hashlib.sha256(uri.encode()).hexdigest()
            return os.path.join(tempfile.gettempdir(), "btrc-lsp-virtual", digest + suffix)
        path = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            path = f"//{parsed.netloc}{path}"
        if cls._WINDOWS_DRIVE_RE.match(path):
            path = path[1:]
        return path

    @staticmethod
    def _diagnostic(
        line: int,
        col: int,
        message: str,
        severity: lsp.DiagnosticSeverity = lsp.DiagnosticSeverity.Error,
        source: str = "btrc",
        token_index: dict[int, list[Token]] | None = None,
        source_text: str = "",
    ) -> lsp.Diagnostic:
        length = 1
        if token_index:
            for token in token_index.get(line, []):
                if token.col <= col < token.col + len(token.value):
                    length = token.col + len(token.value) - col
                    break
        return lsp.Diagnostic(
            range=DocumentText(source_text).protocol_range(line, col, length),
            message=message,
            severity=severity,
            source=source,
        )

    def analyze(self, uri: str, source: str) -> DocumentAnalysis:
        """Run the compiler frontend and semantic analyzer for one document."""

        path = self.path_from_uri(uri)
        result = DocumentAnalysis(uri=uri, source=source, path=path)
        try:
            active = self.workspace.parse_active(path, source)
        except Exception as error:
            result.diagnostics.append(self._diagnostic(1, 1, str(error), source_text=source))
            return result

        result.tokens = active.tokens or None
        token_index = active.token_index() if active.tokens else None
        if active.lex_error:
            error = active.lex_error
            result.diagnostics.append(
                self._diagnostic(error.line, error.col, str(error), token_index=token_index, source_text=source)
            )
            return result
        if active.parse_error:
            error = active.parse_error
            result.diagnostics.append(
                self._diagnostic(error.line, error.col, str(error), token_index=token_index, source_text=source)
            )
            return result

        try:
            composition = self.workspace.compose(active)
        except Exception as error:
            result.diagnostics.append(self._diagnostic(1, 1, str(error), source_text=source))
            return result

        fingerprint = composition.snapshot_fingerprint(uri)
        cached = self.workspace.get_snapshot(path)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        for line, message in composition.import_errors:
            result.diagnostics.append(self._diagnostic(line, 1, message, token_index=token_index, source_text=source))

        result.ast = composition.program
        result.units = composition.units_with_tokens()
        result.graph = composition.graph
        visibility_failures = ImportVisibilityChecker(
            composition.program,
            (),
            composition.graph,
            external_symbol_files=self.workspace.stdlib_symbol_files(),
        ).failures(active_file=path)
        result.visibility_failures = tuple(visibility_failures)
        for failure in visibility_failures:
            result.diagnostics.append(
                self._diagnostic(
                    failure.line,
                    failure.col,
                    failure.message,
                    token_index=token_index,
                    source_text=source,
                )
            )

        try:
            result.analyzed = self.workspace.analyze(composition)
        except (SystemExit, Exception) as error:
            result.diagnostics.append(self._diagnostic(1, 1, str(error), source_text=source))
            return result

        for diagnostic in result.analyzed.diags:
            if diagnostic.file is not None and diagnostic.file != path:
                continue
            severity = (
                lsp.DiagnosticSeverity.Warning if diagnostic.severity == "warning" else lsp.DiagnosticSeverity.Error
            )
            result.diagnostics.append(
                self._diagnostic(
                    diagnostic.line,
                    diagnostic.col,
                    diagnostic.message,
                    severity,
                    token_index=token_index,
                    source_text=source,
                )
            )

        self.workspace.store_snapshot(path, fingerprint, result)
        return result
