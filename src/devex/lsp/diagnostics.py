"""Diagnostic computation for btrc documents.

v2 pipeline: the active document is lexed/parsed in its own coordinate space
(imports blanked, not expanded), imported files and the stdlib come from
cached per-file units, and the analyzer runs over the composed declaration
lists. Every position in an ``AnalysisResult`` is native to its file — there
is no resolved-source mapping.
"""

from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import Program
from src.compiler.python.tokens import Token
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
    name_positions: dict[int, tuple[str, int, int]] = field(default_factory=dict)
    # Lazy per-snapshot caches (built once, reused by every request).
    _caches: dict = field(default_factory=dict, repr=False)


def uri_to_path(uri: str) -> str:
    """Convert file:// URI to filesystem path."""
    parsed = urlparse(uri)
    return unquote(parsed.path)


def _make_diagnostic(
    line: int,
    col: int,
    message: str,
    severity: lsp.DiagnosticSeverity = lsp.DiagnosticSeverity.Error,
    source: str = "btrc",
) -> lsp.Diagnostic:
    """Create an LSP Diagnostic.

    btrc uses 1-based line/col; LSP uses 0-based.
    """
    line_0 = max(0, line - 1)
    col_0 = max(0, col - 1)
    return lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=line_0, character=col_0),
            end=lsp.Position(line=line_0, character=col_0 + 1),
        ),
        message=message,
        severity=severity,
        source=source,
    )


def _collect_name_positions(result: AnalysisResult, units: list[FileUnit]) -> None:
    for unit in units:
        for i, decl in enumerate(unit.decls):
            if i < len(unit.name_positions):
                line, col = unit.name_positions[i]
                result.name_positions[id(decl)] = (unit.path, line, col)
            members = getattr(decl, "members", None)
            member_pos = (
                unit.member_name_positions[i]
                if i < len(unit.member_name_positions)
                else []
            )
            if members and member_pos:
                for m, (mline, mcol) in zip(members, member_pos):
                    result.name_positions[id(m)] = (unit.path, mline, mcol)


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
    if active.lex_error:
        e = active.lex_error
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e)))
        return result
    if active.parse_error:
        e = active.parse_error
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e)))
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
        result.diagnostics.append(_make_diagnostic(line, 1, message))

    result.ast = comp.program
    result.units = comp.units_with_tokens()
    _collect_name_positions(result, comp.stdlib + comp.imported + [comp.active])

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
        result.diagnostics.append(_make_diagnostic(diag.line, diag.col, diag.message, severity))

    WORKSPACE.snapshot_cache[path] = (fingerprint, result)
    return result
