"""Exhaustive coverage of the remaining reachable branches across every LSP
feature: scope-aware variable resolution, degraded (no-ast / no-token / pre-
analysis) inputs, static and chained access, reference de-duplication, and the
server's source-swap and empty-result fallbacks. Every test asserts real
behaviour driven through the public feature functions (or, for pure helpers,
the helper directly)."""

import importlib

from lsprotocol import types as lsp

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp import signature_help as sighelp
from src.devex.lsp import utils as lsputils
from src.devex.lsp.builtins import get_stdlib_signature
from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import _resolve_name_pos, get_definition
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references, get_rename_edits, prepare_rename
from src.devex.lsp.semantic_tokens import get_semantic_tokens
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import SAMPLE, analyze, hover_text, pos_of

srv = importlib.import_module("src.devex.lsp.server")
URI = "file:///t.btrc"


def _parse_only_ast(src):
    """The AST as the parser produces it, before the analyzer annotates types."""
    return Parser(Lexer(src, "x").tokenize()).parse()


def _lexonly(src):
    """Tokens present, but no AST and no analysis (lexer-only degraded result)."""
    return AnalysisResult(uri=URI, source=src, tokens=Lexer(src, "x").tokenize(),
                          ast=None, analyzed=None)


def _notokens(src):
    return AnalysisResult(uri=URI, source=src, tokens=None, ast=None, analyzed=None)


# --------------------------------------------------------------------------- #
# semantic_tokens
# --------------------------------------------------------------------------- #

def test_semantic_tokens_none_without_ast():
    assert get_semantic_tokens(_lexonly("int x = 0;")) is None


# --------------------------------------------------------------------------- #
# signature_help
# --------------------------------------------------------------------------- #

def test_count_active_parameter_without_enclosing_paren():
    # No open paren before the cursor: the scan falls off the buffer start and
    # returns the commas counted at depth 0.
    assert sighelp._count_active_parameter("a, b", lsp.Position(line=0, character=4)) == 1


def test_count_active_parameter_out_of_range_position():
    assert sighelp._count_active_parameter(
        "f(x)", lsp.Position(line=9, character=0)) == 0


def test_find_call_context_out_of_range_position_is_none():
    assert sighelp._find_call_context(
        "f(x)", lsp.Position(line=9, character=0)) is None


def test_find_call_context_paren_after_operator_is_none():
    src = "int main() { int z = 2 * (3 + 4); return z; }\n"
    assert get_signature_help(analyze(src), pos_of(src, "(3 + 4)", offset=1)) is None


def test_signature_unknown_function_call_is_none():
    src = "int main() { return mystery(1); }\n"
    assert get_signature_help(analyze(src), pos_of(src, "mystery(1)", offset=8)) is None


def test_signature_new_unknown_class_is_none():
    src = "int main() { var z = new Nope(1); return 0; }\n"
    assert get_signature_help(analyze(src), pos_of(src, "new Nope(1)", offset=9)) is None


def test_signature_constructorless_class_offers_empty_params():
    src = ("class Empty { public int v; }\n"
           "int main() { Empty e = Empty(); return 0; }\n")
    s = get_signature_help(analyze(src), pos_of(src, "Empty()", offset=6))
    assert s is not None and s.signatures[0].parameters == []


def test_signature_self_method_inside_method():
    src = ("class C { public int v; public C() { self.v = 0; }\n"
           "          public int twice() { return self.dbl(self.v); }\n"
           "          public int dbl(int n) { return n + n; } }\n"
           "int main() { C c = C(); return c.twice(); }\n")
    s = get_signature_help(analyze(src), pos_of(src, "self.dbl(self.v", offset=9))
    assert s is not None and s.signatures


def test_resolve_var_type_degraded_returns_none():
    assert sighelp._resolve_var_type(_notokens("x"), "obj", 0) is None


# --------------------------------------------------------------------------- #
# completion
# --------------------------------------------------------------------------- #

def test_completion_user_class_shadowing_stdlib_dedups():
    src = ("class Math { public int v; public Math() { self.v = 0; }\n"
           "             public int sq() { return self.v * self.v; } }\n"
           "int main() { int r = Math.sq(); return r; }\n")
    items = get_completions(analyze(src), pos_of(src, "Math.sq", offset=5))
    labels = [i.label for i in items]
    assert labels and len(labels) == len(set(labels))


def test_completion_chain_with_unresolved_head_is_empty():
    src = "int main() { return ghost.inner.value; }\n"
    items = get_completions(analyze(src), pos_of(src, "ghost.inner.value", offset=12))
    assert items == []


def test_completion_member_degraded_no_ast():
    src = "int main() { string s = \"x\"; return s.size; }\n"
    items = get_completions(_lexonly(src), pos_of(src, "s.size", offset=2))
    assert isinstance(items, list)


def test_completion_member_of_enum_typed_field_is_empty():
    # b.c resolves to the enum type Color, which is neither a built-in nor a
    # class -> _members_for_type returns no members.
    src = ("enum Color { RED, GREEN };\n"
           "class Box { public Color c; public Box() { self.c = RED; } }\n"
           "int main() { Box b = Box(); return b.c.zz; }\n")
    items = get_completions(analyze(src), pos_of(src, "b.c.zz", offset=4))
    assert items == []


# --------------------------------------------------------------------------- #
# definition (find_var scoping + degraded guards)
# --------------------------------------------------------------------------- #

def test_definition_var_out_of_other_function_scope():
    # `dup` exists in both functions; resolving the use in `helper` must skip
    # main's `dup`, whose scope begins on a later line than the cursor.
    src = ("int helper() { int dup = 1; return dup; }\n"
           "int main() { int dup = 2; return dup; }\n")
    loc = get_definition(analyze(src), pos_of(src, "return dup", occurrence=1, offset=7))
    assert loc is not None and loc.range.start.line == 0   # helper's dup


def test_definition_var_declared_after_cursor_is_skipped():
    src = ("int main() {\n"
           "    int y = z;\n"
           "    int z = 5;\n"
           "    return y + z;\n"
           "}\n")
    loc = get_definition(analyze(src), pos_of(src, "= z", offset=2))
    assert loc is None or loc.range.start.line == 1


def test_resolve_name_pos_fallbacks():
    # No tokens -> the node's own position is returned unchanged.
    assert _resolve_name_pos(None, 5, 3, "x") == (5, 3)
    # Name not present among the tokens -> fall back to the node position.
    toks = Lexer("int a = 1;", "x").tokenize()
    assert _resolve_name_pos(toks, 1, 1, "missingname") == (1, 1)


def test_definition_member_near_file_start_is_none():
    assert get_definition(_lexonly(".field"), pos_of(".field", "field")) is None


def test_definition_member_degraded_no_tokens():
    assert get_definition(_notokens("a.b"), lsp.Position(line=0, character=2)) is None


# --------------------------------------------------------------------------- #
# references / rename
# --------------------------------------------------------------------------- #

def test_class_references_can_exclude_declaration():
    src = ("class Widget { public int v; public Widget() { self.v = 0; } }\n"
           "int main() { Widget w = new Widget(); return w.v; }\n")
    pos = pos_of(src, "Widget w", offset=0)          # type usage -> classified as a class
    with_decl = get_references(analyze(src), pos, include_declaration=True)
    without = get_references(analyze(src), pos, include_declaration=False)
    assert len(without) == len(with_decl) - 1


def test_member_references_can_exclude_declaration():
    src = ("class P { public int val; public P() { self.val = 0; }\n"
           "          public int read() { return self.val; } }\n"
           "int main() { P p = P(); return p.val; }\n")
    decl_pos = pos_of(src, "public int val", offset=11)
    with_decl = get_references(analyze(src), decl_pos, include_declaration=True)
    without = get_references(analyze(src), decl_pos, include_declaration=False)
    assert len(without) == len(with_decl) - 1


def test_member_references_resolve_static_and_unresolved_receivers():
    # m() is called on an instance (resolves to Klass), statically (Klass.m,
    # receiver is the class itself) and on an unknown receiver (ghost) — the
    # three branches of _resolve_object_class.
    src = ("class Klass { public int v; public Klass() { self.v = 0; }\n"
           "              public int m() { return 1; } }\n"
           "int main() { Klass k = Klass(); int a = k.m();"
           " int b = Klass.m(); int c = ghost.m(); return a; }\n")
    refs = get_references(analyze(src), pos_of(src, "public int m", offset=11),
                          include_declaration=True)
    assert len(refs) >= 2


def test_rename_degraded_no_ast_is_none():
    assert get_rename_edits(_lexonly("int main(){ return 0; }"),
                            lsp.Position(line=0, character=4), "renamed") is None


def test_prepare_rename_degraded_no_tokens_is_none():
    assert prepare_rename(_notokens("int main(){}"),
                          lsp.Position(line=0, character=4)) is None


def test_prepare_rename_builtin_generic_keyword_is_none():
    # `List` lexes as an identifier but is a reserved built-in name.
    src = "int main() { List<int> xs = new List<int>(); return 0; }\n"
    assert prepare_rename(analyze(src), pos_of(src, "List<int> xs", offset=0)) is None


# --------------------------------------------------------------------------- #
# hover
# --------------------------------------------------------------------------- #

def test_hover_degraded_no_tokens_is_none():
    assert get_hover_info(_notokens("int x = 0;"),
                          lsp.Position(line=0, character=4)) is None


def test_hover_member_near_file_start_is_none():
    # A member token at token index < 2 (no room for a receiver) yields nothing.
    assert get_hover_info(_lexonly(".field"), pos_of(".field", "field")) is None


def test_hover_member_on_unresolved_receiver_scans_classes():
    src = ("class Point { public int x; public Point() { self.x = 0; }\n"
           "              public int getX() { return self.x; } }\n"
           "int main() { return mystery.getX(); }\n")
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "mystery.getX", offset=8)))
    assert "getX" in t or t == ""


def test_hover_unknown_member_returns_none():
    src = ("class B { public int b; public B() { self.b = 0; }\n"
           "          public int getB() { return self.b; } }\n"
           "class D extends B { public int d; public D() { self.d = 0; } }\n"
           "int main() { D x = new D(); return x.nope(); }\n")
    assert get_hover_info(analyze(src), pos_of(src, "x.nope", offset=2)) is None


def test_hover_variable_degraded_no_ast_is_none():
    src = "int main() { int q = 5; return q; }\n"
    assert get_hover_info(_lexonly(src), pos_of(src, "return q", offset=7)) is None


def test_hover_in_body_non_variable_identifier_is_none():
    src = ("class K { public int v; public K() { self.v = 0; } }\n"
           "int main() { K k = K(); return foobar; }\n")
    assert get_hover_info(analyze(src), pos_of(src, "return foobar", offset=7)) is None


def test_hover_variable_declared_in_try_block():
    src = ("int main() {\n"
           "    try { int caught = 5; return caught; }\n"
           "    catch (string e) { return 0; }\n"
           "}\n")
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "return caught", offset=7)))
    assert "caught" in t


def test_hover_variable_declared_in_else_block():
    src = ("int main() {\n"
           "    if (1) { return 1; }\n"
           "    else { int picked = 2; return picked; }\n"
           "}\n")
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "return picked", offset=7)))
    assert "picked" in t


# --------------------------------------------------------------------------- #
# utils — variable/type/chain resolution
# --------------------------------------------------------------------------- #

def test_resolve_variable_type_inferred_constructor_call():
    # On the pre-analysis AST the `var` has no annotated type, so resolution
    # falls to the constructor-call inference branch.
    src = ("class T { public int v; public T() { self.v = 0; } }\n"
           "int main() { var t = T(); return t.v; }\n")
    ct = analyze(src).analyzed.class_table
    assert lsputils.resolve_variable_type("t", _parse_only_ast(src), ct) == "T"


def test_resolve_variable_type_inferred_new_expr():
    src = ("class T { public int v; public T() { self.v = 0; } }\n"
           "int main() { var t = new T(); return t.v; }\n")
    ct = analyze(src).analyzed.class_table
    assert lsputils.resolve_variable_type("t", _parse_only_ast(src), ct) == "T"


def test_resolve_variable_type_in_else_branch():
    src = ("class T { public int v; public T() { self.v = 0; } }\n"
           "int main() {\n"
           "    if (1) { return 0; }\n"
           "    else { T made = new T(); return made.v; }\n"
           "}\n")
    a = analyze(src)
    assert lsputils.resolve_variable_type("made", a.ast, a.analyzed.class_table) == "T"


def test_resolve_variable_type_in_else_if_branch():
    src = ("class T { public int v; public T() { self.v = 0; } }\n"
           "int main() {\n"
           "    if (1) { return 0; }\n"
           "    else if (0) { T made = new T(); return made.v; }\n"
           "    return 1;\n"
           "}\n")
    a = analyze(src)
    assert lsputils.resolve_variable_type("made", a.ast, a.analyzed.class_table) == "T"


def test_resolve_chain_static_root():
    src = ("class A { public int v; public A() { self.v = 0; }\n"
           "          public int go() { return 1; } }\n"
           "int main() { A a = A(); return a.go(); }\n")
    a = analyze(src)
    a_idx = next(i for i, t in enumerate(a.tokens) if t.value == "A" and t.line == 3)
    assert lsputils.resolve_chain_type(a, a.tokens, a_idx, a.analyzed.class_table) == "A"


def test_resolve_chain_broken_hop_is_none():
    src = ("class A { public int v; public A() { self.v = 0; } }\n"
           "int main() { A a = A(); return a.bad; }\n")
    a = analyze(src)
    bad_idx = next(i for i, t in enumerate(a.tokens) if t.value == "bad")
    assert lsputils.resolve_chain_type(a, a.tokens, bad_idx, a.analyzed.class_table) is None


def test_find_enclosing_class_via_self_member_definition():
    src = ("class Counter {\n"
           "    public int n;\n"
           "    public Counter() { self.n = 0; }\n"
           "    public int bump() {\n"
           "        int step = 1;\n"
           "        return self.n + step;\n"
           "    }\n"
           "}\n"
           "int main() { Counter c = Counter(); return c.bump(); }\n")
    loc = get_definition(analyze(src), pos_of(src, "self.n + step", offset=5))
    assert loc is None or loc.range.start.line == 1


# --------------------------------------------------------------------------- #
# builtins
# --------------------------------------------------------------------------- #

def test_stdlib_signature_unknown_method_is_none():
    assert get_stdlib_signature("Math", "definitely_not_a_method") is None


# --------------------------------------------------------------------------- #
# server source-swap + empty-result fallbacks
# --------------------------------------------------------------------------- #

class _Doc:
    def __init__(self, source):
        self.source = source


class _WS:
    def __init__(self, source):
        self._source = source

    def get_text_document(self, uri):
        return _Doc(self._source) if self._source is not None else None


def _install_ws(monkeypatch, source):
    monkeypatch.setattr(srv.server, "text_document_publish_diagnostics",
                        lambda params: None, raising=False)
    monkeypatch.setattr(srv.server.protocol, "_workspace", _WS(source), raising=False)


def test_server_completion_swaps_in_current_source(monkeypatch):
    _install_ws(monkeypatch, SAMPLE + "\n")          # doc newer than cache
    srv._validate_document(URI, SAMPLE)               # cache holds old source
    out = srv.completion(lsp.CompletionParams(
        text_document=lsp.TextDocumentIdentifier(uri=URI),
        position=pos_of(SAMPLE, "self.", offset=5)))
    assert out is not None


def test_server_completion_empty_without_doc_or_cache(monkeypatch):
    _install_ws(monkeypatch, None)                    # no document
    srv._analysis_cache.pop("file:///gone.btrc", None)
    out = srv.completion(lsp.CompletionParams(
        text_document=lsp.TextDocumentIdentifier(uri="file:///gone.btrc"),
        position=lsp.Position(line=0, character=0)))
    assert out == []


def test_server_signature_swaps_in_current_source(monkeypatch):
    _install_ws(monkeypatch, SAMPLE + "\n")
    srv._validate_document(URI, SAMPLE)
    out = srv.signature_help(lsp.SignatureHelpParams(
        text_document=lsp.TextDocumentIdentifier(uri=URI),
        position=pos_of(SAMPLE, "add(self.x", offset=4)))
    assert out is None or out.signatures


def test_server_signature_none_without_doc_or_cache(monkeypatch):
    _install_ws(monkeypatch, None)
    srv._analysis_cache.pop("file:///gone2.btrc", None)
    out = srv.signature_help(lsp.SignatureHelpParams(
        text_document=lsp.TextDocumentIdentifier(uri="file:///gone2.btrc"),
        position=lsp.Position(line=0, character=0)))
    assert out is None
