"""Drive the pygls server handlers directly — seed the document caches and stub
the transport/workspace so the server glue is covered without a live client."""

import importlib

from lsprotocol import types as lsp

from src.devex.lsp.tests.lsphelp import SAMPLE, pos_of

srv = importlib.import_module("src.devex.lsp.server")

URI = "file:///t.btrc"


class _Doc:
    def __init__(self, source):
        self.source = source


class _Workspace:
    def __init__(self, source):
        self._source = source

    def get_text_document(self, uri):
        return _Doc(self._source)


def _seed(monkeypatch, source=SAMPLE):
    """Populate the analysis caches + stub transport/workspace; return captured
    diagnostics publishes."""
    published = []
    monkeypatch.setattr(srv.server, "text_document_publish_diagnostics",
                        lambda params: published.append(params), raising=False)
    # server.workspace is a read-only property over protocol._workspace.
    monkeypatch.setattr(srv.server.protocol, "_workspace", _Workspace(source),
                        raising=False)
    srv._validate_document(URI, source)
    return published


def _ident():
    return lsp.TextDocumentIdentifier(uri=URI)


def test_validate_document_publishes(monkeypatch):
    published = _seed(monkeypatch, "int main() { string s = \"x; }\n")  # lexer error
    assert published and published[-1].uri == URI
    assert published[-1].diagnostics  # at least one diagnostic


def test_did_open_handler(monkeypatch):
    _seed(monkeypatch)
    srv.did_open(lsp.DidOpenTextDocumentParams(
        text_document=lsp.TextDocumentItem(
            uri=URI, language_id="btrc", version=1, text=SAMPLE)))
    assert URI in srv._analysis_cache


def test_goto_definition_handler(monkeypatch):
    _seed(monkeypatch)
    loc = srv.goto_definition(lsp.TextDocumentPositionParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p.getX", offset=2)))
    assert loc is not None and loc.range.start.line == 7


def test_hover_handler(monkeypatch):
    _seed(monkeypatch)
    h = srv.hover(lsp.HoverParams(
        text_document=_ident(), position=pos_of(SAMPLE, "Point p", offset=1)))
    assert h is not None


def test_document_symbol_handler(monkeypatch):
    _seed(monkeypatch)
    syms = srv.document_symbol(lsp.DocumentSymbolParams(text_document=_ident()))
    assert any(s.name == "Point" for s in syms)


def test_completion_handler(monkeypatch):
    _seed(monkeypatch)
    items = srv.completion(lsp.CompletionParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p.getX", offset=2)))
    assert any(it.label == "getX" for it in items)


def test_signature_help_handler(monkeypatch):
    _seed(monkeypatch)
    sig = srv.signature_help(lsp.SignatureHelpParams(
        text_document=_ident(), position=pos_of(SAMPLE, "add(self.x", offset=4)))
    assert sig is not None and sig.signatures


def test_references_handler(monkeypatch):
    _seed(monkeypatch)
    refs = srv.find_references(lsp.ReferenceParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p.getX", offset=2),
        context=lsp.ReferenceContext(include_declaration=True)))
    assert refs and len(refs) >= 2


def test_rename_handlers(monkeypatch):
    _seed(monkeypatch)
    rng = srv.prepare_rename_handler(lsp.PrepareRenameParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p = Point", offset=0)))
    assert rng is not None
    we = srv.rename(lsp.RenameParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p = Point", offset=0),
        new_name="q"))
    assert we is not None


def test_semantic_tokens_handler(monkeypatch):
    _seed(monkeypatch)
    toks = srv.semantic_tokens_full(lsp.SemanticTokensParams(text_document=_ident()))
    assert toks is not None and toks.data


def test_did_close_clears_cache(monkeypatch):
    _seed(monkeypatch)
    srv.did_close(lsp.DidCloseTextDocumentParams(text_document=_ident()))
    assert URI not in srv._analysis_cache
    assert URI not in srv._good_analysis_cache


def test_did_change_revalidates_from_workspace(monkeypatch):
    _seed(monkeypatch)
    srv._analysis_cache.pop(URI, None)
    srv.did_change(lsp.DidChangeTextDocumentParams(
        text_document=lsp.VersionedTextDocumentIdentifier(uri=URI, version=2),
        content_changes=[]))
    assert URI in srv._analysis_cache  # re-read from (stubbed) workspace + analyzed


def test_did_save_revalidates_from_workspace(monkeypatch):
    _seed(monkeypatch)
    srv._analysis_cache.pop(URI, None)
    srv.did_save(lsp.DidSaveTextDocumentParams(text_document=_ident()))
    assert URI in srv._analysis_cache


def test_definition_falls_back_to_last_good(monkeypatch):
    _seed(monkeypatch)                                   # good SAMPLE cached
    srv._validate_document(URI, "class { broken")        # transient parse error
    # current analysis has no AST → _get_best_result returns the last good one
    loc = srv.goto_definition(lsp.TextDocumentPositionParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p.getX", offset=2)))
    assert loc is not None and loc.range.start.line == 7


def test_completion_falls_back_to_last_good(monkeypatch):
    _seed(monkeypatch)
    srv._validate_document(URI, "class { broken")        # analyzed is None now
    items = srv.completion(lsp.CompletionParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p.getX", offset=2)))
    assert any(it.label == "getX" for it in items)


_ORIGIN = lsp.Position(line=0, character=0)


def test_read_handlers_return_empty_without_cached_document(monkeypatch):
    _seed(monkeypatch)
    srv._analysis_cache.clear()
    srv._good_analysis_cache.clear()
    pp = lsp.TextDocumentPositionParams(text_document=_ident(), position=_ORIGIN)
    assert srv.goto_definition(pp) is None
    assert srv.hover(lsp.HoverParams(text_document=_ident(), position=_ORIGIN)) is None
    assert srv.document_symbol(lsp.DocumentSymbolParams(text_document=_ident())) == []
    assert srv.find_references(lsp.ReferenceParams(
        text_document=_ident(), position=_ORIGIN,
        context=lsp.ReferenceContext(include_declaration=True))) == []
    assert srv.prepare_rename_handler(lsp.PrepareRenameParams(
        text_document=_ident(), position=_ORIGIN)) is None
    assert srv.rename(lsp.RenameParams(
        text_document=_ident(), position=_ORIGIN, new_name="x")) is None
    assert srv.semantic_tokens_full(lsp.SemanticTokensParams(
        text_document=_ident())) is None


def test_completion_and_signature_compute_when_uncached(monkeypatch):
    # caches empty but the workspace still has the source → handlers compute it
    _seed(monkeypatch)
    srv._analysis_cache.clear()
    srv._good_analysis_cache.clear()
    items = srv.completion(lsp.CompletionParams(
        text_document=_ident(), position=pos_of(SAMPLE, "p.getX", offset=2)))
    assert any(it.label == "getX" for it in items)
    srv._analysis_cache.clear()
    sig = srv.signature_help(lsp.SignatureHelpParams(
        text_document=_ident(), position=pos_of(SAMPLE, "add(self.x", offset=4)))
    assert sig is not None and sig.signatures
