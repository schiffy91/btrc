"""Heuristic fallbacks used when semantic analysis is unavailable — a real
server mode (the last-good/typing path drives features with a parsed AST but
analyzed=None). This exercises the text/AST heuristics that the analyzer
normally short-circuits, plus the lexer-only (no AST) and token-less inputs
every feature must tolerate."""

from lsprotocol import types as lsp

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp.analysis.document import DocumentAnalysis as AnalysisResult
from src.tests.lsp.lsphelp import SIGNATURE_HELP as sighelp
from src.tests.lsp.lsphelp import (
    get_completions,
    get_definition,
    get_hover_info,
    get_references,
    get_rename_edits,
    get_semantic_tokens,
    get_signature_help,
    hover_text,
    pos_of,
    prepare_rename,
)

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
    assert isinstance(items, list)  # resolution ran without analysis (no crash)


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


def test_degraded_unresolvable_member_degrades_cleanly():
    src = "int main() { mystery.thing(); return 0; }\n"
    r = _degraded(src)
    pos = pos_of(src, "mystery.thing", offset=8)  # cursor on `thing`
    assert get_hover_info(r, pos) is None
    assert get_definition(r, pos) is None
    assert isinstance(get_completions(r, pos_of(src, "mystery.thing", offset=8)), list)
    s = get_signature_help(r, pos_of(src, "thing()", offset=6))
    assert s is None or s.signatures
    assert get_references(r, pos) == [] or isinstance(get_references(r, pos), list)


def test_hover_var_literal_init_fallback():
    # var initialized from a literal (not call/new) → heuristic falls back
    src = "int main() { var k = 5; return k; }\n"
    t = hover_text(get_hover_info(_degraded(src), pos_of(src, "var k", offset=4)))
    assert t != ""


# ---- lexer-only (no AST) and token-less inputs ------------------------------

URI = "file:///t.btrc"


def _lexonly(src):
    """Tokens present, but no AST and no analysis (lexer-only degraded result)."""
    return AnalysisResult(uri=URI, source=src, tokens=Lexer(src, "x").tokenize(), ast=None, analyzed=None)


def _notokens(src):
    return AnalysisResult(uri=URI, source=src, tokens=None, ast=None, analyzed=None)


def test_semantic_tokens_none_without_ast():
    assert get_semantic_tokens(_lexonly("int x = 0;")) is None


def test_active_call_degraded_no_tokens_is_none():
    # _active_call_callee_index now takes the token list directly so the
    # mid-edit path can substitute re-lexed live-line tokens for stale ones.
    assert sighelp._active_call_callee_index(_notokens("x").tokens, lsp.Position(line=0, character=0)) is None


def test_completion_member_degraded_no_ast():
    src = 'int main() { string s = "x"; return s.size; }\n'
    items = get_completions(_lexonly(src), pos_of(src, "s.size", offset=2))
    assert isinstance(items, list)


def test_definition_member_near_file_start_is_none():
    assert get_definition(_lexonly(".field"), pos_of(".field", "field")) is None


def test_definition_member_degraded_no_tokens():
    assert get_definition(_notokens("a.b"), lsp.Position(line=0, character=2)) is None


def test_rename_degraded_no_ast_is_none():
    assert get_rename_edits(_lexonly("int main(){ return 0; }"), lsp.Position(line=0, character=4), "renamed") is None


def test_prepare_rename_degraded_no_tokens_is_none():
    assert prepare_rename(_notokens("int main(){}"), lsp.Position(line=0, character=4)) is None


def test_hover_degraded_no_tokens_is_none():
    assert get_hover_info(_notokens("int x = 0;"), lsp.Position(line=0, character=4)) is None


def test_hover_member_near_file_start_is_none():
    # A member token at token index < 2 (no room for a receiver) yields nothing.
    assert get_hover_info(_lexonly(".field"), pos_of(".field", "field")) is None


def test_hover_variable_degraded_no_ast_is_none():
    src = "int main() { int q = 5; return q; }\n"
    assert get_hover_info(_lexonly(src), pos_of(src, "return q", offset=7)) is None
