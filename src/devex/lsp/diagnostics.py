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
    """Run the compiler front-end and return diagnostics."""
    result = AnalysisResult(uri=uri, source=source)
    file_path = uri_to_path(uri)

    try:
        frontend = compile_frontend(source, file_path)
        result.tokens = frontend.tokens
        result.ast = frontend.user_program or frontend.program
        result.analyzed = frontend.analyzed
    except LexerError as e:
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e)))
        return result
    except ParseError as e:
        result.diagnostics.append(_make_diagnostic(e.line, e.col, str(e)))
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

    for err_str in result.analyzed.errors:
        m = _ANALYZER_ERROR_RE.match(err_str)
        if m:
            msg, line_s, col_s = m.group(1), m.group(2), m.group(3)
            result.diagnostics.append(_make_diagnostic(int(line_s), int(col_s), msg))
        else:
            result.diagnostics.append(_make_diagnostic(1, 1, err_str))

    return result
