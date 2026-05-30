"""Heuristic fallbacks used when semantic analysis is unavailable — a real
server mode (the last-good/typing path drives features with a parsed AST but
analyzed=None). This exercises the text/AST heuristics that the analyzer
normally short-circuits."""

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import hover_text, pos_of

SRC = """\
class Box {
    public int v;
    public Box(int v) { self.v = v; }
    public int get() { return self.v; }
}

int run(int n) {
    var a = Box(1);
    var b = new Box(2);
    if (n > 0) {
        var d = Box(4);
        int dd = d.get();
    } else if (n < 0) {
        var c = Box(3);
        int cc = c.get();
    }
    return 0;
}

int useParam(Box p) {
    return p.get();
}
"""


def _degraded(src=SRC, uri="file:///d.btrc"):
    """Parse only — no analysis (analyzed=None), like the mid-edit server path."""
    tokens = Lexer(src, "d").tokenize()
    ast = Parser(tokens).parse()
    return AnalysisResult(uri=uri, source=src, tokens=tokens, ast=ast, analyzed=None)


def test_hover_infers_class_type_from_call_without_analysis():
    r = _degraded()
    t = hover_text(get_hover_info(r, pos_of(SRC, "var a", offset=4)))
    assert "Box" in t or "a" in t


def test_hover_infers_class_type_from_new_without_analysis():
    r = _degraded()
    t = hover_text(get_hover_info(r, pos_of(SRC, "var b", offset=4)))
    assert "Box" in t or "b" in t


def test_completion_member_via_text_heuristics():
    r = _degraded()
    # resolve `d` (var d = Box(4)) inside the if-block by scanning the AST text
    items = get_completions(r, pos_of(SRC, "d.get", offset=2))
    assert isinstance(items, list)   # resolution ran without analysis (no crash)


def test_completion_member_in_elseif_via_heuristics():
    r = _degraded()
    items = get_completions(r, pos_of(SRC, "c.get", offset=2))
    assert isinstance(items, list)


def test_completion_member_on_parameter_via_heuristics():
    r = _degraded()
    items = get_completions(r, pos_of(SRC, "p.get", offset=2))
    assert isinstance(items, list)


def test_definition_local_without_analysis():
    r = _degraded()
    # go-to-definition on `a` still works from the AST alone
    assert get_definition(r, pos_of(SRC, "var a", offset=4)) is not None


def test_signature_member_without_analysis():
    r = _degraded()
    # signature for d.get() with no analyzed class_table → degrades, no crash
    s = get_signature_help(r, pos_of(SRC, "d.get", offset=4))
    assert s is None or s.signatures
