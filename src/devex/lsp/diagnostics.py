"""Diagnostic computation for btrc documents.

Runs the compiler pipeline (lexer -> parser -> analyzer) on source text
and converts errors into LSP Diagnostic objects.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, unquote

from lsprotocol import types as lsp

from src.compiler.python.lexer import Lexer, LexerError
from src.compiler.python.parser import Parser, ParseError
from src.compiler.python.analyzer import Analyzer, AnalyzedProgram
from src.compiler.python.ast_nodes import Program
from src.compiler.python.tokens import Token
from src.compiler.python.main import resolve_includes

# Regex to parse analyzer error strings: "message at line:col"
_ANALYZER_ERROR_RE = re.compile(r"^(.+) at (\d+):(\d+)$")


@dataclass
class AnalysisResult:
    """Cached result of analyzing a document."""

    uri: str
    source: str
    diagnostics: list[lsp.Diagnostic] = field(default_factory=list)
    tokens: Optional[list[Token]] = None
    ast: Optional[Program] = None
    analyzed: Optional[AnalyzedProgram] = None


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


def compute_diagnostics(uri: str, source: str) -> AnalysisResult:
    """Run the compiler pipeline and return diagnostics."""
    result = AnalysisResult(uri=uri, source=source)
    file_path = uri_to_path(uri)
    filename = os.path.basename(file_path)

    # Resolve #include directives (best-effort)
    try:
        resolved_source = resolve_includes(source, file_path)
    except (SystemExit, Exception):
        resolved_source = source

    # Lexing
    try:
        lexer = Lexer(resolved_source, filename)
        tokens = lexer.tokenize()
        result.tokens = tokens
    except LexerError as e:
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e)))
        return result

    # Parsing
    try:
        parser = Parser(tokens)
        program = parser.parse()
        result.ast = program
    except ParseError as e:
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e)))
        return result

    # Semantic analysis
    analyzer = Analyzer()
    analyzed = analyzer.analyze(program)
    result.analyzed = analyzed

    for err_str in analyzed.errors:
        m = _ANALYZER_ERROR_RE.match(err_str)
        if m:
            msg, line_s, col_s = m.group(1), m.group(2), m.group(3)
            result.diagnostics.append(_make_diagnostic(int(line_s), int(col_s), msg))
        else:
            result.diagnostics.append(_make_diagnostic(1, 1, err_str))

    return result
