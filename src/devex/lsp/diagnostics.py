"""Diagnostic computation for btrc documents.

v2 pipeline: the active document is lexed/parsed in its own coordinate space
(imports blanked, not expanded), imported files and the stdlib come from
cached per-file units, and the analyzer runs over the composed declaration
lists. Every position in an ``AnalysisResult`` is native to its file — there
is no resolved-source mapping.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.request import url2pathname

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import Program
from src.compiler.python.frontend.dependencies import SourceDependencyGraph
from src.compiler.python.frontend.visibility import (
    ImportVisibilityChecker,
    ImportVisibilityFailure,
)
from src.compiler.python.tokens import Token
from src.devex.lsp.text_coordinates import protocol_range
from src.devex.lsp.units import FileUnit
from src.devex.lsp.workspace import Workspace

# Process-wide workspace: unit caches survive across documents and requests.
WORKSPACE = Workspace()


@dataclass
class AnalysisResult:
    """Snapshot of one analyzed document.

    ``tokens`` are the active file's tokens only, in native positions.
    ``ast`` is the composed program (stdlib + imports + active file); each
    top-level decl carries ``source_file`` provenance.
    """

    uri: str
    source: str
    diagnostics: list[lsp.Diagnostic] = field(default_factory=list)
    tokens: list[Token] | None = None
    ast: Program | None = None
    analyzed: AnalyzedProgram | None = None
    source_positions: list[tuple[str, int]] = field(default_factory=list)  # legacy, unused
    path: str = ""
    units: list[FileUnit] = field(default_factory=list)  # active + imported (with tokens)
    graph: SourceDependencyGraph = field(default_factory=SourceDependencyGraph)
    visibility_failures: tuple[ImportVisibilityFailure, ...] = ()
    # When the server swaps `source` to the live (mid-edit) buffer, this holds
    # the source the tokens/ast were computed from. None means source IS the
    # analyzed snapshot.
    snapshot_source: str | None = field(default=None, repr=False)
    # Lazy per-snapshot caches (built once, reused by every request).
    _caches: dict = field(default_factory=dict, repr=False)


def line_changed_since_snapshot(result: AnalysisResult, line0: int) -> bool:
    """True when the live buffer's 0-based line *line0* differs from the
    analyzed snapshot's same line — token positions on that line are stale."""
    if result.snapshot_source is None:
        return False
    return _line_at(result.source, line0) != _line_at(result.snapshot_source, line0)


def analysis_is_current(result: AnalysisResult) -> bool:
    """Whether token/AST positions describe the source exposed to the client."""
    return result.snapshot_source is None


def analysis_positions_are_stable(result: AnalysisResult) -> bool:
    """Whether every analyzed position still points at the same source prefix."""
    return result.snapshot_source is None or result.source.startswith(result.snapshot_source)


def analysis_is_current_at(result: AnalysisResult, line: int) -> bool:
    """Whether a point request can safely use tokens from one source line."""
    return analysis_positions_are_stable(result) or not line_changed_since_snapshot(result, line)


def _line_at(text: str, line0: int) -> str:
    lines = text.split("\n")
    return lines[line0] if 0 <= line0 < len(lines) else ""


_WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:(?:[/\\]|$)")


def uri_to_path(uri: str) -> str:
    """Convert file:// URI to a filesystem path.

    POSIX URIs decode byte-identically to ``unquote(urlparse(uri).path)``;
    Windows drive URIs (``file:///C:/...``) additionally lose the spurious
    leading slash so the result is a usable native path.
    """
    parsed = urlparse(uri)
    if parsed.scheme and parsed.scheme != "file":
        suffix = os.path.splitext(parsed.path)[1] or ".btrc"
        digest = hashlib.sha256(uri.encode()).hexdigest()
        return os.path.join(tempfile.gettempdir(), "btrc-lsp-virtual", digest + suffix)
    path = url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc != "localhost":
        path = f"//{parsed.netloc}{path}"
    if _WINDOWS_DRIVE_RE.match(path):
        path = path[1:]
    return path


def _make_diagnostic(
    line: int,
    col: int,
    message: str,
    severity: lsp.DiagnosticSeverity = lsp.DiagnosticSeverity.Error,
    source: str = "btrc",
    token_index: dict[int, list[Token]] | None = None,
    source_text: str = "",
) -> lsp.Diagnostic:
    """Create an LSP Diagnostic.

    btrc uses 1-based line/col; LSP uses 0-based. When *token_index* (line ->
    tokens) is given and a token covers (line, col), the range widens to that
    token's end; otherwise it stays one character wide.
    """
    length = 1
    if token_index:
        for tok in token_index.get(line, []):
            if tok.col <= col < tok.col + len(tok.value):
                length = tok.col + len(tok.value) - col
                break
    return lsp.Diagnostic(
        range=protocol_range(source_text, line, col, length),
        message=message,
        severity=severity,
        source=source,
    )


def compute_diagnostics(uri: str, source: str) -> AnalysisResult:
    """Run the per-file front-end and return diagnostics for this document."""
    path = uri_to_path(uri)
    result = AnalysisResult(uri=uri, source=source, path=path)

    try:
        active = WORKSPACE.parse_active(path, source)
    except Exception as e:  # defensive: lexer/parser raising something unexpected
        result.diagnostics.append(_make_diagnostic(1, 1, str(e), source_text=source))
        return result

    result.tokens = active.tokens or None
    token_index = active.token_index() if active.tokens else None
    if active.lex_error:
        e = active.lex_error
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e), token_index=token_index, source_text=source))
        return result
    if active.parse_error:
        e = active.parse_error
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e), token_index=token_index, source_text=source))
        return result

    try:
        comp = WORKSPACE.compose(active)
    except Exception as e:
        result.diagnostics.append(_make_diagnostic(1, 1, str(e), source_text=source))
        return result

    # Identical composition (same active text, same imports, same stdlib) →
    # reuse the previous snapshot outright. Re-analyzing the same AST twice is
    # both wasted work and unsafe: the analyzer upgrades types in place.
    fingerprint = comp.snapshot_fingerprint(uri)
    cached = WORKSPACE.get_snapshot(path)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]

    for line, message in comp.import_errors:
        result.diagnostics.append(_make_diagnostic(line, 1, message, token_index=token_index, source_text=source))

    result.ast = comp.program
    result.units = comp.units_with_tokens()
    result.graph = comp.graph

    visibility_failures = ImportVisibilityChecker(
        comp.program,
        (),
        comp.graph,
        external_symbol_files=WORKSPACE.stdlib_symbol_files(),
    ).failures(active_file=path)
    result.visibility_failures = tuple(visibility_failures)
    for failure in visibility_failures:
        result.diagnostics.append(
            _make_diagnostic(
                failure.line,
                failure.col,
                failure.message,
                token_index=token_index,
                source_text=source,
            )
        )

    try:
        result.analyzed = WORKSPACE.analyze(comp)
    except (SystemExit, Exception) as e:
        result.diagnostics.append(_make_diagnostic(1, 1, str(e), source_text=source))
        return result

    for diag in result.analyzed.diags:
        if diag.file is not None and diag.file != path:
            continue  # imported/stdlib diagnostics belong to their own document
        severity = lsp.DiagnosticSeverity.Warning if diag.severity == "warning" else lsp.DiagnosticSeverity.Error
        result.diagnostics.append(
            _make_diagnostic(
                diag.line,
                diag.col,
                diag.message,
                severity,
                token_index=token_index,
                source_text=source,
            )
        )

    WORKSPACE.store_snapshot(path, fingerprint, result)
    return result
