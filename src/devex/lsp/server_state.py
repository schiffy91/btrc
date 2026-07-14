"""Shared state for the btrc language server.

Owns the pygls server instance, the per-document analysis caches, and the
snapshot-selection helpers used by feature handlers. Validation scheduling
lives in server.py; both modules share the locks defined here.
"""

import logging
import os
import threading
from itertools import count

from pygls.lsp.server import LanguageServer

from src.devex.lsp.diagnostics import (
    WORKSPACE,
    AnalysisResult,
    compute_diagnostics,
    uri_to_path,
)

logger = logging.getLogger("btrc-lsp")

server = LanguageServer("btrc-lsp", "0.1.0")

# Cache: uri -> AnalysisResult (latest, may have errors)
_analysis_cache: dict[str, AnalysisResult] = {}

# Cache: uri -> AnalysisResult (last successful analysis with AST + class_table)
_good_analysis_cache: dict[str, AnalysisResult] = {}

_validate_lock = threading.Lock()  # single-flight: one pipeline run at a time
_state_lock = threading.Lock()  # guards generations/timers/open set + publishes
_generations: dict[str, int] = {}
_timers: dict[str, object] = {}
_open_uris: set[str] = set()
_document_sources: dict[str, str] = {}
_versions: dict[str, int] = {}
_generation_counter = count(1)


def _overlay_provider(path: str) -> str | None:
    """Serve unsaved editor buffers when imported files are open in the editor."""
    with _state_lock:
        sources = list(_document_sources.items())
    try:
        workspace_sources = [(uri, document.source) for uri, document in list(server.workspace.text_documents.items())]
    except Exception:
        workspace_sources = []
    known_uris = {uri for uri, _source in sources}
    sources.extend(item for item in workspace_sources if item[0] not in known_uris)
    identity = _path_identity(path)
    for uri, source in sources:
        if _path_identity(uri_to_path(uri)) == identity:
            return source
    return None


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


WORKSPACE.overlay_provider = _overlay_provider


def _get_best_result(uri: str) -> AnalysisResult | None:
    """Return the best available analysis for *uri*.

    Prefers the current (possibly broken) analysis when it has a valid AST.
    Falls back to the last successful analysis so that features like
    go-to-definition, hover, and find-references keep working while the
    user is typing and the file has transient parse errors.
    """
    with _state_lock:
        result = _analysis_cache.get(uri)
        if result and result.ast and result.analyzed:
            return result
        good = _good_analysis_cache.get(uri)
        if good:
            return good
        return result  # may still have tokens even without AST


def _compute_uncached(uri: str, source: str) -> AnalysisResult:
    """Pipeline run for a feature request that found no cached analysis.

    Takes the same single-flight lock as scheduled validations — the analyzer
    mutates shared cached unit decls, so unlocked concurrent runs corrupt
    them — and stores into both caches like a validation would.
    """
    with _validate_lock:
        result = compute_diagnostics(uri, source)
    with _state_lock:
        _analysis_cache[uri] = result
        if result.analyzed and result.ast:
            _good_analysis_cache[uri] = result
    return result


def _result_with_current_source(
    uri: str,
    *,
    compute_if_missing: bool = True,
) -> AnalysisResult | None:
    """Best analysis for *uri*, with `source` swapped to the live buffer.

    Completion and signature help extract text around the cursor from
    ``result.source``; while the user types, the live buffer is ahead of the
    last analyzed snapshot. ``snapshot_source`` keeps the analyzed text so
    providers can detect lines whose tokens are stale.
    """
    try:
        doc = server.workspace.get_text_document(uri)
    except Exception:
        doc = None
    current_source = doc.source if doc else None

    with _state_lock:
        result = _analysis_cache.get(uri)
        if result and not result.analyzed:
            good = _good_analysis_cache.get(uri)
            if good:
                result = good

    if not result and current_source and compute_if_missing:
        result = _compute_uncached(uri, current_source)

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
            snapshot_source=result.source,
            _caches=result._caches,
        )
    return result


def _warm_workspace():  # pragma: no cover - startup optimization
    """Pre-parse stdlib units so the first didOpen analysis is fast."""
    try:
        WORKSPACE.stdlib_units()
    except Exception:
        logger.exception("stdlib warmup failed")
