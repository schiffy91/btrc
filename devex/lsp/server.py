#!/usr/bin/env python3
"""btrc Language Server.

Provides diagnostics, document symbols, hover, code completion, and
signature help for .btrc files by reusing the compiler's lexer, parser,
and analyzer.
"""

import sys
import logging
from pathlib import Path

# Add project root to sys.path so we can import src.compiler.python
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lsprotocol import types as lsp  # noqa: E402
from pygls.lsp.server import LanguageServer  # noqa: E402

from devex.lsp.diagnostics import AnalysisResult, compute_diagnostics  # noqa: E402
from devex.lsp.symbols import get_document_symbols  # noqa: E402
from devex.lsp.hover import get_hover_info  # noqa: E402
from devex.lsp.definition import get_definition  # noqa: E402
from devex.lsp.completion import get_completions  # noqa: E402
from devex.lsp.signature_help import get_signature_help  # noqa: E402
from devex.lsp.references import get_references, get_rename_edits, prepare_rename  # noqa: E402
from devex.lsp.semantic_tokens import get_semantic_tokens, LEGEND  # noqa: E402

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("btrc-lsp")

server = LanguageServer("btrc-lsp", "0.1.0")

# Cache: uri -> AnalysisResult (latest, may have errors)
_analysis_cache: dict[str, AnalysisResult] = {}

# Cache: uri -> AnalysisResult (last successful analysis with AST + class_table)
_good_analysis_cache: dict[str, AnalysisResult] = {}


def _validate_document(uri: str, source: str):
    """Run the compiler pipeline and publish diagnostics."""
    result = compute_diagnostics(uri, source)
    _analysis_cache[uri] = result
    # Keep a copy of the last successful analysis for completion fallback
    if result.analyzed and result.ast:
        _good_analysis_cache[uri] = result
    server.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=uri, diagnostics=result.diagnostics)
    )


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: lsp.DidOpenTextDocumentParams):
    _validate_document(
        params.text_document.uri,
        params.text_document.text,
    )


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(params: lsp.DidChangeTextDocumentParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    _validate_document(params.text_document.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    _validate_document(params.text_document.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def did_close(params: lsp.DidCloseTextDocumentParams):
    uri = params.text_document.uri
    _analysis_cache.pop(uri, None)
    _good_analysis_cache.pop(uri, None)
    server.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
    )


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(params: lsp.DocumentSymbolParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result and result.ast:
        return get_document_symbols(result)
    return []


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
def hover(params: lsp.HoverParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result:
        return get_hover_info(result, params.position)
    return None


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def goto_definition(params: lsp.TextDocumentPositionParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result:
        return get_definition(result, params.position)
    return None


@server.feature(
    lsp.TEXT_DOCUMENT_COMPLETION,
    lsp.CompletionOptions(trigger_characters=['.'])
)
def completion(params: lsp.CompletionParams):
    uri = params.text_document.uri

    # Get current document source for extracting text around cursor
    doc = server.workspace.get_text_document(uri)
    current_source = doc.source if doc else None

    # Prefer the current analysis result, but fall back to the last good one
    # when the current source has parse errors (common while typing)
    result = _analysis_cache.get(uri)
    if result and not result.analyzed:
        good = _good_analysis_cache.get(uri)
        if good:
            # Use the good analysis but with the current source text
            # so text-before-cursor extraction works on the live buffer
            result = AnalysisResult(
                uri=uri,
                source=current_source or good.source,
                diagnostics=good.diagnostics,
                tokens=good.tokens,
                ast=good.ast,
                analyzed=good.analyzed,
            )

    if not result and current_source:
        result = compute_diagnostics(uri, current_source)
        _analysis_cache[uri] = result

    if result:
        # Always use current source for cursor context if available
        if current_source and result.source != current_source:
            result = AnalysisResult(
                uri=result.uri,
                source=current_source,
                diagnostics=result.diagnostics,
                tokens=result.tokens,
                ast=result.ast,
                analyzed=result.analyzed,
            )
        return get_completions(result, params.position)
    return []


@server.feature(
    lsp.TEXT_DOCUMENT_SIGNATURE_HELP,
    lsp.SignatureHelpOptions(trigger_characters=['(', ','])
)
def signature_help(params: lsp.SignatureHelpParams):
    uri = params.text_document.uri

    # Get current document source for cursor context
    doc = server.workspace.get_text_document(uri)
    current_source = doc.source if doc else None

    # Prefer the current analysis result, but fall back to the last good one
    # when the current source has parse errors (common while typing arguments)
    result = _analysis_cache.get(uri)
    if result and not result.analyzed:
        good = _good_analysis_cache.get(uri)
        if good:
            result = AnalysisResult(
                uri=uri,
                source=current_source or good.source,
                diagnostics=good.diagnostics,
                tokens=good.tokens,
                ast=good.ast,
                analyzed=good.analyzed,
            )

    if not result and current_source:
        result = compute_diagnostics(uri, current_source)
        _analysis_cache[uri] = result

    if result:
        # Always use current source for cursor context if available
        if current_source and result.source != current_source:
            result = AnalysisResult(
                uri=result.uri,
                source=current_source,
                diagnostics=result.diagnostics,
                tokens=result.tokens,
                ast=result.ast,
                analyzed=result.analyzed,
            )
        return get_signature_help(result, params.position)
    return None


@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
def find_references(params: lsp.ReferenceParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result:
        include_decl = params.context.include_declaration if params.context else True
        return get_references(result, params.position, include_decl)
    return []


@server.feature(
    lsp.TEXT_DOCUMENT_RENAME,
)
def rename(params: lsp.RenameParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result:
        return get_rename_edits(result, params.position, params.new_name)
    return None


@server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename_handler(params: lsp.PrepareRenameParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result:
        return prepare_rename(result, params.position)
    return None


@server.feature(
    lsp.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    lsp.SemanticTokensOptions(legend=LEGEND, full=True),
)
def semantic_tokens_full(params: lsp.SemanticTokensParams):
    result = _analysis_cache.get(params.text_document.uri)
    if result:
        return get_semantic_tokens(result)
    return None


if __name__ == "__main__":
    server.start_io()
