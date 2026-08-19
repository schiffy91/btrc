"""textDocument/documentHighlight: scope-correct, active-file occurrences."""

from lsprotocol import types as lsp

from src.devex.lsp.protocol.server import BtrcLanguageServer
from src.tests.lsp.lsphelp import get_document_highlights
from src.tests.lsp.lsphelp import analyze, pos_of

srv = BtrcLanguageServer(debounce_seconds=0)

TWO_LOCALS = """\
int f() {
    int total = 0;
    total = total + 1;
    return total;
}

int g() {
    int total = 99;
    return total;
}
"""


def _starts(highlights):
    return {(h.range.start.line, h.range.start.character) for h in highlights}


def test_local_highlights_are_scope_correct():
    r = analyze(TWO_LOCALS)
    pos = pos_of(TWO_LOCALS, "total", occurrence=1, offset=1)  # inside f
    hls = get_document_highlights(r, pos)
    starts = _starts(hls)
    # All four uses of f's `total` are on lines 1-3 (0-based).
    assert starts == {(1, 8), (2, 4), (2, 12), (3, 11)}
    # g's same-named `total` (line 7 decl, line 8 use) must NOT appear.
    assert all(line < 6 for line, _col in starts)


def test_other_function_local_not_highlighted():
    r = analyze(TWO_LOCALS)
    pos = pos_of(TWO_LOCALS, "total", occurrence=6, offset=1)  # g's `return total`
    hls = get_document_highlights(r, pos)
    starts = _starts(hls)
    # Only g's two occurrences (lines 7 and 8).
    assert starts == {(7, 8), (8, 11)}


def test_write_vs_read_kind():
    r = analyze(TWO_LOCALS)
    pos = pos_of(TWO_LOCALS, "total", occurrence=1, offset=1)
    hls = get_document_highlights(r, pos)
    by_start = {(h.range.start.line, h.range.start.character): h.kind for h in hls}
    # decl `int total = 0` and the `total = ...` assignment are Writes.
    assert by_start[(1, 8)] == lsp.DocumentHighlightKind.Write
    assert by_start[(2, 4)] == lsp.DocumentHighlightKind.Write
    # `total + 1` and `return total` are Reads.
    assert by_start[(2, 12)] == lsp.DocumentHighlightKind.Read
    assert by_start[(3, 11)] == lsp.DocumentHighlightKind.Read


CLASS_SRC = """\
class Point {
    public int x;
    public int getX() { return self.x; }
    public int twice() { return self.x + self.x; }
}
"""


def test_class_name_highlight():
    r = analyze(CLASS_SRC)
    pos = pos_of(CLASS_SRC, "Point", occurrence=1, offset=1)
    hls = get_document_highlights(r, pos)
    # The class name occurs once (its declaration) in this file.
    assert (0, 6) in _starts(hls)


def test_no_highlight_off_identifier():
    r = analyze(CLASS_SRC)
    # Position on a brace, not an identifier.
    assert get_document_highlights(r, lsp.Position(line=0, character=12)) == []


def test_handler():
    r = analyze(TWO_LOCALS)
    srv._good_analysis_cache["file:///t.btrc"] = r
    srv._analysis_cache["file:///t.btrc"] = r
    pos = pos_of(TWO_LOCALS, "total", occurrence=1, offset=1)
    out = srv.document_highlight(
        lsp.TextDocumentPositionParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///t.btrc"),
            position=pos,
        )
    )
    assert out and len(out) == 4
    srv._analysis_cache.clear()
    srv._good_analysis_cache.clear()
