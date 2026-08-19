"""Language-server protocol composition root.

``BtrcLanguageServer`` owns the transport, compiler workspace, document
snapshots, validation scheduler, and feature providers for one server process.
No process-wide mutable language-server state lives outside this object.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from functools import partial, update_wrapper
from itertools import count

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from src.devex.lsp.analysis.document import DocumentAnalysis, DocumentAnalyzer
from src.devex.lsp.analysis.resolution import SemanticResolver
from src.devex.lsp.catalog.builtins import BuiltinCatalog
from src.devex.lsp.features.code_actions import CodeActionProvider
from src.devex.lsp.features.completion import CompletionProvider
from src.devex.lsp.features.hover import HoverProvider
from src.devex.lsp.features.navigation import NavigationProvider
from src.devex.lsp.features.semantic_tokens import LEGEND, SemanticTokenProvider
from src.devex.lsp.features.signature_help import SignatureHelpProvider
from src.devex.lsp.features.symbols import SymbolProvider
from src.devex.lsp.workspace.workspace import Workspace


class BtrcLanguageServer(LanguageServer):
    """Retained protocol server and owner of one complete LSP object graph."""

    DEFAULT_DEBOUNCE_SECONDS = 0.2
    MAX_DEBOUNCE_SECONDS = 5.0

    def __init__(
        self,
        *,
        debounce_seconds: float | None = None,
        compiler_workspace: Workspace | None = None,
    ) -> None:
        super().__init__("btrc-lsp", "0.1.0")
        self.logger = logging.getLogger("btrc-lsp")
        self.debounce_seconds = self.DEFAULT_DEBOUNCE_SECONDS if debounce_seconds is None else debounce_seconds

        self.compiler_workspace = compiler_workspace or Workspace()
        self.analyzer = DocumentAnalyzer(self.compiler_workspace)
        self.catalog = BuiltinCatalog()
        self.resolver = SemanticResolver(self.catalog)
        self.navigation = NavigationProvider(self.resolver, self.compiler_workspace)
        self.completion = CompletionProvider(self.catalog, self.resolver)
        self.signature_help_provider = SignatureHelpProvider(self.catalog, self.resolver)
        self.hover_provider = HoverProvider(self.catalog, self.resolver, self.navigation)
        self.semantic_tokens_provider = SemanticTokenProvider(self.resolver, self.navigation)
        self.symbols = SymbolProvider(self.resolver)
        self.code_actions = CodeActionProvider(
            self.catalog,
            self.resolver,
            self.navigation,
            self.compiler_workspace,
        )

        self._analysis_cache: dict[str, DocumentAnalysis] = {}
        self._good_analysis_cache: dict[str, DocumentAnalysis] = {}
        self._validate_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._generations: dict[str, int] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._open_uris: set[str] = set()
        self._document_sources: dict[str, str] = {}
        self._versions: dict[str, int] = {}
        self._generation_counter = count(1)

        self.compiler_workspace.overlay_provider = self._overlay_source
        self._register_features()

    @classmethod
    def from_environment(cls) -> BtrcLanguageServer:
        return cls(debounce_seconds=cls.parse_debounce_seconds(os.environ.get("BTRC_LSP_DEBOUNCE")))

    @classmethod
    def parse_debounce_seconds(cls, value: str | None) -> float:
        """Return a finite interactive debounce delay or the safe default."""

        if value is None:
            return cls.DEFAULT_DEBOUNCE_SECONDS
        try:
            seconds = float(value)
        except ValueError:
            return cls.DEFAULT_DEBOUNCE_SECONDS
        if not math.isfinite(seconds) or not 0 <= seconds <= cls.MAX_DEBOUNCE_SECONDS:
            return cls.DEFAULT_DEBOUNCE_SECONDS
        return seconds

    def _register_features(self) -> None:
        """Bind protocol methods to this retained server instance."""

        threaded_open = self.thread()(self._protocol_handler(self.did_open))
        threaded_change = self.thread()(self._protocol_handler(self.did_change))
        threaded_save = self.thread()(self._protocol_handler(self.did_save))
        self.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(threaded_open)
        self.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(threaded_change)
        self.feature(lsp.TEXT_DOCUMENT_DID_SAVE)(threaded_save)
        self.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)(self._protocol_handler(self.did_close))
        self.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)(self._protocol_handler(self.document_symbol))
        self.feature(lsp.TEXT_DOCUMENT_HOVER)(self._protocol_handler(self.hover))
        self.feature(lsp.TEXT_DOCUMENT_DEFINITION)(self._protocol_handler(self.goto_definition))
        self.feature(
            lsp.TEXT_DOCUMENT_COMPLETION,
            lsp.CompletionOptions(trigger_characters=[".", ">"]),
        )(self._protocol_handler(self.complete))
        self.feature(
            lsp.TEXT_DOCUMENT_SIGNATURE_HELP,
            lsp.SignatureHelpOptions(trigger_characters=["(", ","]),
        )(self._protocol_handler(self.signature_help))
        self.feature(lsp.TEXT_DOCUMENT_REFERENCES)(self._protocol_handler(self.find_references))
        self.feature(lsp.TEXT_DOCUMENT_RENAME)(self._protocol_handler(self.rename))
        self.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)(self._protocol_handler(self.prepare_rename))
        self.feature(
            lsp.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
            lsp.SemanticTokensRegistrationOptions(legend=LEGEND, full=True),
        )(self._protocol_handler(self.semantic_tokens_full))
        self.feature(lsp.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)(self._protocol_handler(self.document_highlight))
        self.feature(lsp.WORKSPACE_SYMBOL)(self._protocol_handler(self.workspace_symbol))
        self.feature(
            lsp.TEXT_DOCUMENT_CODE_ACTION,
            lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
        )(self._protocol_handler(self.code_action))

    @staticmethod
    def _protocol_handler(method):
        """Return a metadata-writable callable retaining one bound method."""

        return update_wrapper(partial(method), method)

    @staticmethod
    def _path_identity(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    def _overlay_source(self, path: str) -> str | None:
        """Serve unsaved buffers when an imported document is open."""

        with self._state_lock:
            sources = list(self._document_sources.items())
        try:
            editor_sources = [(uri, document.source) for uri, document in list(self.workspace.text_documents.items())]
        except Exception:
            editor_sources = []
        known_uris = {uri for uri, _source in sources}
        sources.extend(item for item in editor_sources if item[0] not in known_uris)
        identity = self._path_identity(path)
        for uri, source in sources:
            if self._path_identity(self.analyzer.path_from_uri(uri)) == identity:
                return source
        return None

    def _best_result(self, uri: str) -> DocumentAnalysis | None:
        with self._state_lock:
            result = self._analysis_cache.get(uri)
            if result and result.ast and result.analyzed:
                return result
            good = self._good_analysis_cache.get(uri)
            return good or result

    def _compute_uncached(self, uri: str, source: str) -> DocumentAnalysis:
        with self._validate_lock:
            result = self.analyzer.analyze(uri, source)
        with self._state_lock:
            self._analysis_cache[uri] = result
            if result.analyzed and result.ast:
                self._good_analysis_cache[uri] = result
        return result

    def _result_with_current_source(
        self,
        uri: str,
        *,
        compute_if_missing: bool = True,
    ) -> DocumentAnalysis | None:
        try:
            document = self.workspace.get_text_document(uri)
        except Exception:
            document = None
        current_source = document.source if document else None
        with self._state_lock:
            result = self._analysis_cache.get(uri)
            if result and not result.analyzed:
                result = self._good_analysis_cache.get(uri) or result
        if result is None and current_source is not None and compute_if_missing:
            result = self._compute_uncached(uri, current_source)
        if result is None:
            return None
        return result if current_source is None else result.with_live_source(current_source)

    def _cached_current_result(self, params) -> DocumentAnalysis | None:
        return self._result_with_current_source(params.text_document.uri, compute_if_missing=False)

    def _validate_document(
        self,
        uri: str,
        source: str,
        generation: int | None = None,
    ) -> None:
        if generation is None:
            with self._state_lock:
                self._open_uris.add(uri)
                generation = next(self._generation_counter)
                self._generations[uri] = generation
                self._document_sources[uri] = source
        with self._validate_lock:
            result = self.analyzer.analyze(uri, source)
        with self._state_lock:
            if self._generations.get(uri) != generation or uri not in self._open_uris:
                return
            self._analysis_cache[uri] = result
            if result.analyzed and result.ast:
                self._good_analysis_cache[uri] = result
            self.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=result.diagnostics)
            )

    def _schedule_validation(
        self,
        uri: str,
        source: str,
        delay: float,
        version: int | None = None,
    ) -> None:
        with self._state_lock:
            current_version = self._versions.get(uri)
            if version is not None and current_version is not None and version < current_version:
                return
            if version is not None:
                self._versions[uri] = version
            self._open_uris.add(uri)
            self._document_sources[uri] = source
            generation = next(self._generation_counter)
            self._generations[uri] = generation
            previous = self._timers.pop(uri, None)
        if previous:
            previous.cancel()
        if delay <= 0:
            self._validate_document(uri, source, generation)
            return

        timer = threading.Timer(delay, self._run_scheduled_validation, args=(uri, source, generation))
        timer.daemon = True
        with self._state_lock:
            self._timers[uri] = timer
        timer.start()

    def _run_scheduled_validation(self, uri: str, source: str, generation: int) -> None:
        with self._state_lock:
            if self._generations.get(uri) != generation:
                return
            self._timers.pop(uri, None)
        try:
            self._validate_document(uri, source, generation)
        except Exception:  # pragma: no cover - protocol-process defense
            self.logger.exception("validation failed for %s", uri)

    def did_open(self, params: lsp.DidOpenTextDocumentParams) -> None:
        self._schedule_validation(
            params.text_document.uri,
            params.text_document.text,
            0,
            params.text_document.version,
        )

    def did_change(self, params: lsp.DidChangeTextDocumentParams) -> None:
        document = self.workspace.get_text_document(params.text_document.uri)
        self._schedule_validation(
            params.text_document.uri,
            document.source,
            self.debounce_seconds,
            params.text_document.version,
        )

    def did_save(self, params: lsp.DidSaveTextDocumentParams) -> None:
        document = self.workspace.get_text_document(params.text_document.uri)
        self._schedule_validation(params.text_document.uri, document.source, 0)

    def did_close(self, params: lsp.DidCloseTextDocumentParams) -> None:
        uri = params.text_document.uri
        with self._state_lock:
            self._generations.pop(uri, None)
            self._open_uris.discard(uri)
            self._document_sources.pop(uri, None)
            self._versions.pop(uri, None)
            timer = self._timers.pop(uri, None)
            self._analysis_cache.pop(uri, None)
            self._good_analysis_cache.pop(uri, None)
        if timer:
            timer.cancel()
        self.compiler_workspace.close_document(self.analyzer.path_from_uri(uri))
        self.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[]))

    def document_symbol(self, params: lsp.DocumentSymbolParams):
        result = self._best_result(params.text_document.uri)
        return self.symbols.get_document_symbols(result) if result and result.ast else []

    def hover(self, params: lsp.HoverParams):
        result = self._cached_current_result(params)
        return self.hover_provider.get_hover_info(result, params.position) if result else None

    def goto_definition(self, params: lsp.TextDocumentPositionParams):
        result = self._cached_current_result(params)
        return self.navigation.get_definition(result, params.position) if result else None

    def complete(self, params: lsp.CompletionParams):
        result = self._result_with_current_source(params.text_document.uri)
        return self.completion.get_completions(result, params.position) if result else []

    def signature_help(self, params: lsp.SignatureHelpParams):
        result = self._result_with_current_source(params.text_document.uri)
        return self.signature_help_provider.get_signature_help(result, params.position) if result else None

    def find_references(self, params: lsp.ReferenceParams):
        result = self._cached_current_result(params)
        if result is None:
            return []
        include_declaration = params.context.include_declaration if params.context else True
        return self.navigation.get_references(result, params.position, include_declaration)

    def rename(self, params: lsp.RenameParams):
        result = self._cached_current_result(params)
        return self.navigation.get_rename_edits(result, params.position, params.new_name) if result else None

    def prepare_rename(self, params: lsp.PrepareRenameParams):
        result = self._cached_current_result(params)
        return self.navigation.prepare_rename(result, params.position) if result else None

    def semantic_tokens_full(self, params: lsp.SemanticTokensParams):
        result = self._best_result(params.text_document.uri)
        return self.semantic_tokens_provider.get_semantic_tokens(result) if result else None

    def document_highlight(self, params: lsp.TextDocumentPositionParams):
        result = self._cached_current_result(params)
        return self.navigation.get_document_highlights(result, params.position) if result else []

    def workspace_symbol(self, params: lsp.WorkspaceSymbolParams):
        return self.symbols.get_workspace_symbols(self.compiler_workspace, params.query or "")

    def code_action(self, params: lsp.CodeActionParams):
        result = self._cached_current_result(params)
        return self.code_actions.get_code_actions(result, params) if result else []

    def warm_workspace(self) -> None:  # pragma: no cover - startup optimization
        try:
            self.compiler_workspace.stdlib_units()
        except Exception:
            self.logger.exception("stdlib warmup failed")

    def start_io(self, *args, **kwargs):  # pragma: no cover - real-client entry point
        threading.Thread(target=self.warm_workspace, daemon=True).start()
        return super().start_io(*args, **kwargs)
