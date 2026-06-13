"""Diagnostic computation for btrc documents.

v2 pipeline: the active document is lexed/parsed in its own coordinate space
(imports blanked, not expanded), imported files and the stdlib come from
cached per-file units, and the analyzer runs over the composed declaration
lists. Every position in an ``AnalysisResult`` is native to its file — there
is no resolved-source mapping.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.request import url2pathname

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import Program
from src.compiler.python.tokens import Token
from src.devex.lsp.units import FileUnit, unit_line_index
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
    path = url2pathname(parsed.path)
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
) -> lsp.Diagnostic:
    """Create an LSP Diagnostic.

    btrc uses 1-based line/col; LSP uses 0-based. When *token_index* (line ->
    tokens) is given and a token covers (line, col), the range widens to that
    token's end; otherwise it stays one character wide.
    """
    line_0 = max(0, line - 1)
    col_0 = max(0, col - 1)
    length = 1
    if token_index:
        for tok in token_index.get(line, []):
            if tok.col <= col < tok.col + len(tok.value):
                length = tok.col + len(tok.value) - col
                break
    return lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=line_0, character=col_0),
            end=lsp.Position(line=line_0, character=col_0 + length),
        ),
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
        result.diagnostics.append(_make_diagnostic(1, 1, str(e)))
        return result

    result.tokens = active.tokens or None
    token_index = unit_line_index(active) if active.tokens else None
    if active.lex_error:
        e = active.lex_error
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e), token_index=token_index))
        return result
    if active.parse_error:
        e = active.parse_error
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e), token_index=token_index))
        return result

    try:
        comp = WORKSPACE.compose(active)
    except Exception as e:
        result.diagnostics.append(_make_diagnostic(1, 1, str(e)))
        return result

    # Identical composition (same active text, same imports, same stdlib) →
    # reuse the previous snapshot outright. Re-analyzing the same AST twice is
    # both wasted work and unsafe: the analyzer upgrades types in place.
    fingerprint = (
        uri,
        active.content_hash,
        tuple((u.path, u.content_hash) for u in comp.imported),
        tuple(u.path for u in comp.stdlib),
    )
    cached = WORKSPACE.snapshot_cache.get(path)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]

    for line, message in comp.import_errors:
        result.diagnostics.append(_make_diagnostic(line, 1, message, token_index=token_index))

    result.ast = comp.program
    result.units = comp.units_with_tokens()

    try:
        result.analyzed = WORKSPACE.analyze(comp)
    except (SystemExit, Exception) as e:
        result.diagnostics.append(_make_diagnostic(1, 1, str(e)))
        return result

    for diag in result.analyzed.diags:
        if diag.file is not None and diag.file != path:
            continue  # imported/stdlib diagnostics belong to their own document
        severity = (
            lsp.DiagnosticSeverity.Warning
            if diag.severity == "warning"
            else lsp.DiagnosticSeverity.Error
        )
        result.diagnostics.append(
            _make_diagnostic(diag.line, diag.col, diag.message, severity, token_index=token_index)
        )

    WORKSPACE.snapshot_cache[path] = (fingerprint, result)
    return result
