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

from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.diagnostics import compute_diagnostics
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references, get_rename_edits, prepare_rename
from src.devex.lsp.semantic_tokens import LEGEND, get_semantic_tokens
from src.devex.lsp.server_state import (
    _analysis_cache,
    _generations,
    _get_best_result,
    _good_analysis_cache,
    _open_uris,
    _result_with_current_source,
    _state_lock,
    _timers,
    _validate_lock,
    _warm_workspace,
    server,
)
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.symbols import get_document_symbols

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("btrc-lsp")

# Debounce window for didChange re-analysis. 0 validates inline (used by tests).
DEBOUNCE_SECONDS = float(os.environ.get("BTRC_LSP_DEBOUNCE", "0.2"))


def _validate_document(uri: str, source: str, generation: int | None = None):
    """Run the compiler pipeline and publish diagnostics (synchronous).

    *generation* is the document generation claimed at schedule time; direct
    calls (didOpen, tests) claim a fresh one. Before caching and publishing,
    the run re-checks under the state lock that it is still the current
    generation and the document is still open — a newer edit or a didClose
    that landed while the pipeline ran makes this result stale, and a stale
    publish must never overwrite a newer one.
    """
    if generation is None:
        with _state_lock:
            _open_uris.add(uri)
            _generations[uri] = _generations.get(uri, 0) + 1
            generation = _generations[uri]
    with _validate_lock:
        result = compute_diagnostics(uri, source)
    with _state_lock:
        if _generations.get(uri) != generation or uri not in _open_uris:
            return  # superseded mid-run or document closed: drop
        _analysis_cache[uri] = result
        # Keep a copy of the last successful analysis for feature fallback
        if result.analyzed and result.ast:
            _good_analysis_cache[uri] = result
        # Publish under the lock so a didClose (which bumps the generation
        # first) can never be outrun by this now-stale publish.
        server.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=result.diagnostics)
        )


def _schedule_validation(uri: str, source: str, delay: float):
    """Debounced validation: a newer edit supersedes any pending/running one."""
    with _state_lock:
        _open_uris.add(uri)
        _generations[uri] = _generations.get(uri, 0) + 1
        generation = _generations[uri]
        old = _timers.pop(uri, None)
    if old:
        old.cancel()

    if delay <= 0:
        _validate_document(uri, source, generation=generation)
        return

    def run():
        with _state_lock:
            if _generations.get(uri) != generation:
                return  # superseded while waiting
            _timers.pop(uri, None)
        try:
            _validate_document(uri, source, generation=generation)
        except Exception:  # pragma: no cover - defensive
            logger.exception("validation failed for %s", uri)

    timer = threading.Timer(delay, run)
    timer.daemon = True
    with _state_lock:
        _timers[uri] = timer
    timer.start()


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
        _open_uris.discard(uri)  # in-flight runs must not repopulate caches
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


def main():  # pragma: no cover - stdio entry point for a real client
    threading.Thread(target=_warm_workspace, daemon=True).start()
    server.start_io()


if __name__ == "__main__":  # pragma: no cover - stdio entry point for a real client
    main()
