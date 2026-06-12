#!/usr/bin/env python3
"""btrc Language Server.

Provides diagnostics, document symbols, hover, code completion, and
signature help for .btrc files by reusing the compiler's lexer, parser,
and analyzer.

Responsiveness model: document edits schedule a debounced re-analysis on a
background thread (superseded runs are cancelled by generation); feature
requests read the latest completed snapshot and never run the pipeline.
"""

import logging
import os
import sys
import threading
from pathlib import Path

# Add project root to sys.path so we can import src.compiler.python
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if PROJECT_ROOT not in sys.path:  # pragma: no cover - import-time bootstrap
    sys.path.insert(0, PROJECT_ROOT)

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.diagnostics import WORKSPACE, AnalysisResult, compute_diagnostics
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references, get_rename_edits, prepare_rename
from src.devex.lsp.semantic_tokens import LEGEND, get_semantic_tokens
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.symbols import get_document_symbols

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("btrc-lsp")

server = LanguageServer("btrc-lsp", "0.1.0")

# Cache: uri -> AnalysisResult (latest, may have errors)
_analysis_cache: dict[str, AnalysisResult] = {}

# Cache: uri -> AnalysisResult (last successful analysis with AST + class_table)
_good_analysis_cache: dict[str, AnalysisResult] = {}

# Debounce window for didChange re-analysis. 0 validates inline (used by tests).
DEBOUNCE_SECONDS = float(os.environ.get("BTRC_LSP_DEBOUNCE", "0.2"))

_validate_lock = threading.Lock()  # single-flight: one pipeline run at a time
_state_lock = threading.Lock()
_generations: dict[str, int] = {}
_timers: dict[str, threading.Timer] = {}


def _overlay_provider(path: str) -> str | None:
    """Serve unsaved editor buffers when imported files are open in the editor."""
    try:
        documents = server.workspace.text_documents
    except Exception:
        return None
    for uri, doc in documents.items():
        from src.devex.lsp.diagnostics import uri_to_path

        if os.path.abspath(uri_to_path(uri)) == path:
            return doc.source
    return None


WORKSPACE.overlay_provider = _overlay_provider


def _validate_document(uri: str, source: str):
    """Run the compiler pipeline and publish diagnostics (synchronous)."""
    with _validate_lock:
        result = compute_diagnostics(uri, source)
        _analysis_cache[uri] = result
        # Keep a copy of the last successful analysis for feature fallback
        if result.analyzed and result.ast:
            _good_analysis_cache[uri] = result
    server.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=uri, diagnostics=result.diagnostics)
    )


def _schedule_validation(uri: str, source: str, delay: float):
    """Debounced validation: a newer edit supersedes any pending/running one."""
    with _state_lock:
        _generations[uri] = _generations.get(uri, 0) + 1
        generation = _generations[uri]
        old = _timers.pop(uri, None)
    if old:
        old.cancel()

    if delay <= 0:
        _validate_document(uri, source)
        return

    def run():
        with _state_lock:
            if _generations.get(uri) != generation:
                return  # superseded while waiting
            _timers.pop(uri, None)
        try:
            _validate_document(uri, source)
        except Exception:  # pragma: no cover - defensive
            logger.exception("validation failed for %s", uri)

    timer = threading.Timer(delay, run)
    timer.daemon = True
    with _state_lock:
        _timers[uri] = timer
    timer.start()


def _get_best_result(uri: str) -> AnalysisResult | None:
    """Return the best available analysis for *uri*.

    Prefers the current (possibly broken) analysis when it has a valid AST.
    Falls back to the last successful analysis so that features like
    go-to-definition, hover, and find-references keep working while the
    user is typing and the file has transient parse errors.
    """
    result = _analysis_cache.get(uri)
    if result and result.ast and result.analyzed:
        return result
    good = _good_analysis_cache.get(uri)
    if good:
        return good
    return result  # may still have tokens even without AST


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
@server.thread()
def did_open(params: lsp.DidOpenTextDocumentParams):
    _validate_document(
        params.text_document.uri,
        params.text_document.text,
    )


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
@server.thread()
def did_change(params: lsp.DidChangeTextDocumentParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    _schedule_validation(params.text_document.uri, doc.source, DEBOUNCE_SECONDS)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
@server.thread()
def did_save(params: lsp.DidSaveTextDocumentParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    _schedule_validation(params.text_document.uri, doc.source, 0)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def did_close(params: lsp.DidCloseTextDocumentParams):
    uri = params.text_document.uri
    with _state_lock:
        _generations[uri] = _generations.get(uri, 0) + 1  # cancel pending runs
        timer = _timers.pop(uri, None)
    if timer:
        timer.cancel()
    _analysis_cache.pop(uri, None)
    _good_analysis_cache.pop(uri, None)
    server.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[]))


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(params: lsp.DocumentSymbolParams):
    result = _get_best_result(params.text_document.uri)
    if result and result.ast:
        return get_document_symbols(result)
    return []


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
def hover(params: lsp.HoverParams):
    result = _get_best_result(params.text_document.uri)
    if result:
        return get_hover_info(result, params.position)
    return None


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def goto_definition(params: lsp.TextDocumentPositionParams):
    result = _get_best_result(params.text_document.uri)
    if result:
        return get_definition(result, params.position)
    return None


def _result_with_current_source(uri: str) -> AnalysisResult | None:
    """Best analysis for *uri*, with `source` swapped to the live buffer.

    Completion and signature help extract text around the cursor from
    ``result.source``; while the user types, the live buffer is ahead of the
    last analyzed snapshot.
    """
    doc = server.workspace.get_text_document(uri)
    current_source = doc.source if doc else None

    result = _analysis_cache.get(uri)
    if result and not result.analyzed:
        good = _good_analysis_cache.get(uri)
        if good:
            result = good

    if not result and current_source:
        result = compute_diagnostics(uri, current_source)
        _analysis_cache[uri] = result

    if not result:
        return None

    if current_source and result.source != current_source:
        result = AnalysisResult(
            uri=result.uri,
            source=current_source,
            diagnostics=result.diagnostics,
            tokens=result.tokens,
            ast=result.ast,
            analyzed=result.analyzed,
            source_positions=result.source_positions,
            path=result.path,
            units=result.units,
            name_positions=result.name_positions,
            _caches=result._caches,
        )
    return result


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION, lsp.CompletionOptions(trigger_characters=[".", ">"]))
def completion(params: lsp.CompletionParams):
    result = _result_with_current_source(params.text_document.uri)
    if result:
        return get_completions(result, params.position)
    return []


@server.feature(
    lsp.TEXT_DOCUMENT_SIGNATURE_HELP,
    lsp.SignatureHelpOptions(trigger_characters=["(", ","]),
)
def signature_help(params: lsp.SignatureHelpParams):
    result = _result_with_current_source(params.text_document.uri)
    if result:
        return get_signature_help(result, params.position)
    return None


@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
def find_references(params: lsp.ReferenceParams):
    result = _get_best_result(params.text_document.uri)
    if result:
        include_decl = params.context.include_declaration if params.context else True
        return get_references(result, params.position, include_decl)
    return []


@server.feature(
    lsp.TEXT_DOCUMENT_RENAME,
)
def rename(params: lsp.RenameParams):
    result = _get_best_result(params.text_document.uri)
    if result:
        return get_rename_edits(result, params.position, params.new_name)
    return None


@server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename_handler(params: lsp.PrepareRenameParams):
    result = _get_best_result(params.text_document.uri)
    if result:
        return prepare_rename(result, params.position)
    return None


@server.feature(
    lsp.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    lsp.SemanticTokensRegistrationOptions(legend=LEGEND, full=True),
)
def semantic_tokens_full(params: lsp.SemanticTokensParams):
    result = _get_best_result(params.text_document.uri)
    if result:
        return get_semantic_tokens(result)
    return None


def _warm_workspace():  # pragma: no cover - startup optimization
    """Pre-parse stdlib units so the first didOpen analysis is fast."""
    try:
        WORKSPACE.stdlib_units()
    except Exception:
        logger.exception("stdlib warmup failed")


def main():  # pragma: no cover - stdio entry point for a real client
    threading.Thread(target=_warm_workspace, daemon=True).start()
    server.start_io()


if __name__ == "__main__":  # pragma: no cover - stdio entry point for a real client
    main()
