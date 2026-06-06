"""Diagnostic computation for btrc documents."""

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

from src.compiler.python import frontend as _frontend
from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import Program
from src.compiler.python.frontend import (
    FrontendVisibilityError,
    IncludeResolutionError,
    compile_frontend,
)
from src.compiler.python.lexer import LexerError
from src.compiler.python.parser.core import ParseError
from src.compiler.python.tokens import Token

# Regex to parse analyzer error strings: "message at line:col"
_ANALYZER_ERROR_RE = re.compile(r"^(.+) at (\d+):(\d+)$")
Analyzer = _frontend.Analyzer


@dataclass
class AnalysisResult:
    """Cached result of analyzing a document."""

    uri: str
    source: str
    diagnostics: list[lsp.Diagnostic] = field(default_factory=list)
    tokens: list[Token] | None = None
    ast: Program | None = None
    analyzed: AnalyzedProgram | None = None
    source_positions: list[tuple[str, int]] = field(default_factory=list)


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


def _append_analyzer_messages(
    result: AnalysisResult,
    messages: list[str],
    severity: lsp.DiagnosticSeverity,
) -> None:
    for message in messages:
        m = _ANALYZER_ERROR_RE.match(message)
        if m:
            msg, line_s, col_s = m.group(1), m.group(2), m.group(3)
            mapped = _map_source_position(result, int(line_s), int(col_s))
            if mapped is not None:
                line, col = mapped
                result.diagnostics.append(_make_diagnostic(line, col, msg, severity))
        else:
            result.diagnostics.append(_make_diagnostic(1, 1, message, severity))


def _map_source_position(
    result: AnalysisResult,
    line: int,
    col: int,
) -> tuple[int, int] | None:
    """Map a compiler-resolved line back to this document's original line.

    Imported-file diagnostics are not published on the importing document; the
    imported document gets its own diagnostics when opened.
    """
    if not result.source_positions:
        return (line, col)
    if line < 1 or line > len(result.source_positions):
        return (line, col)

    source_file, source_line = result.source_positions[line - 1]
    if source_file != uri_to_path(result.uri):
        return None
    return (source_line, col)


def _load_source_positions(source: str, file_path: str) -> list[tuple[str, int]]:
    try:
        frontend_source = _frontend.resolve_frontend_source(
            source,
            file_path,
            include_stdlib=False,
        )
    except Exception:
        return []
    return frontend_source.source_positions


def _append_mapped_diagnostic(
    result: AnalysisResult,
    line: int,
    col: int,
    message: str,
    severity: lsp.DiagnosticSeverity = lsp.DiagnosticSeverity.Error,
) -> None:
    mapped = _map_source_position(result, line, col)
    if mapped is None:
        return
    result.diagnostics.append(_make_diagnostic(mapped[0], mapped[1], message, severity))


def compute_diagnostics(uri: str, source: str) -> AnalysisResult:
    """Run the compiler front-end and return diagnostics."""
    result = AnalysisResult(uri=uri, source=source)
    file_path = uri_to_path(uri)

    try:
        frontend = compile_frontend(source, file_path)
        result.tokens = frontend.tokens
        result.ast = frontend.user_program or frontend.program
        result.analyzed = frontend.analyzed
        result.source_positions = frontend.source_positions
    except LexerError as e:
        result.source_positions = _load_source_positions(source, file_path)
        _append_mapped_diagnostic(result, e.line, e.col, str(e))
        return result
    except ParseError as e:
        result.source_positions = _load_source_positions(source, file_path)
        _append_mapped_diagnostic(result, e.line, e.col, str(e))
        return result
    except FrontendVisibilityError as e:
        for msg, line, col in e.errors:
            result.diagnostics.append(_make_diagnostic(line, col, msg))
        return result
    except IncludeResolutionError as e:
        result.diagnostics.append(_make_diagnostic(1, 1, str(e)))
        return result
    except (SystemExit, Exception) as e:
        result.diagnostics.append(_make_diagnostic(1, 1, str(e)))
        return result

    _append_analyzer_messages(result, result.analyzed.errors, lsp.DiagnosticSeverity.Error)
    _append_analyzer_messages(result, result.analyzed.warnings, lsp.DiagnosticSeverity.Warning)

    return result
