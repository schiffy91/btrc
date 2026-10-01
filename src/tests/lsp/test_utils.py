"""Direct contract tests for the shared resolution helpers in utils.py."""

from lsprotocol import types as lsp

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr
from src.compiler.python.syntax.tokens import Token, TokenKind
from src.devex.lsp.analysis.resolution import LexicalScopeIndex
from src.tests.lsp.lsphelp import RESOLVER, analyze, pos_of

_CHAIN = (
    "class Inner { public int v; public Inner(int v) { self.v = v; }\n"
    "              public int get() { return self.v; } }\n"
    "class Outer { public Inner inner; public Outer() { self.inner = Inner(1); }\n"
    "              public Inner make() { return self.inner; } }\n"
    "int main() { Outer o = Outer(); return o.make().get(); }\n"
)


def _ast(source: str):
    return Parser(Lexer(source, "x").tokenize()).parse()


def test_resolve_member_type_field_method_builtin_unknown():
    ct = analyze(_CHAIN).analyzed.class_table
    assert RESOLVER.resolve_member_type("Outer", "inner", ct) == "Inner"  # field type
    assert RESOLVER.resolve_member_type("Outer", "make", ct) == "Inner"  # method return type
    assert RESOLVER.resolve_member_type("string", "len", ct) is not None  # builtin member
    assert RESOLVER.resolve_member_type("Nope", "x", ct) is None  # unknown owner
    assert RESOLVER.resolve_member_type("Outer", "ghost", ct) is None  # member not found


def test_resolve_variable_type_decl_forms():
    src = (
        "class Box { public int v; public Box(int v) { self.v = v; } }\n"
        "Box mk() { return Box(1); }\n"
        "int run(Box p) { var a = Box(2); var b = new Box(3); var c = mk(); return 0; }\n"
    )
    r = analyze(src)
    decls, ct = RESOLVER.active_decls(r), r.analyzed.class_table
    assert RESOLVER.resolve_variable_type("a", decls, ct) == "Box"  # constructor call
    assert RESOLVER.resolve_variable_type("b", decls, ct) == "Box"  # new expression
    assert RESOLVER.resolve_variable_type("p", decls, ct) == "Box"  # parameter type


def test_type_repr_none_is_void():
    assert RESOLVER.type_repr(None) == "void"
    assert RESOLVER.type_repr(TypeExpr(base="int")) == "int"
    assert (
        RESOLVER.type_repr(
            TypeExpr(
                base="Map",
                generic_args=[TypeExpr(base="string"), TypeExpr(base="int")],
                pointer_depth=1,
                is_const=True,
                is_nullable=True,
            )
        )
        == "const Map<string, int>*?"
    )


def test_find_token_index_missing_returns_none():
    r = analyze("int main() { return 0; }\n")
    fake = Token(type=TokenKind.IDENT, value="nope", line=999, col=1)
    assert RESOLVER.find_token_index(r.tokens, fake) is None


def test_get_text_before_cursor_out_of_range():
    assert RESOLVER.get_text_before_cursor("a\nb\n", lsp.Position(line=99, character=0)) == ""


def test_find_closing_brace_line_match_and_unbalanced():
    assert LexicalScopeIndex.find_closing_brace_line(["class X {", "    int y;", "}"], 0) == 2
    assert LexicalScopeIndex.find_closing_brace_line(["class X {", "    int y;"], 0) is None


def test_find_enclosing_class_inside_outside_and_none():
    src = "class A {\n    public int m() { return 1; }\n}\nint top() { return 0; }\n"
    ast = _ast(src)
    assert LexicalScopeIndex.find_enclosing_class(ast, 2) == "A"  # 1-based line inside A
    assert LexicalScopeIndex.find_enclosing_class(ast, 4) is None  # top() is not in a class
    assert LexicalScopeIndex.find_enclosing_class(None, 1) is None


def test_find_enclosing_class_from_source_inside_outside_and_none():
    src = "class A {\n    public int m() { return 1; }\n}\n"
    ast = _ast(src)
    assert LexicalScopeIndex.find_enclosing_class_from_source(ast, src, 1) == "A"  # 0-based
    assert LexicalScopeIndex.find_enclosing_class_from_source(ast, src, 3) is None
    assert LexicalScopeIndex.find_enclosing_class_from_source(None, "", 0) is None


def test_body_range_empty_body_uses_fallback():
    ast = _ast("void f() { }\nint main() { return 0; }\n")
    fn = ast.declarations[0]
    start, end = LexicalScopeIndex.body_range(fn.body, fn.line)
    assert end - start >= 1000  # empty body → wide fallback range


def test_body_range_walks_elseif_and_switch():
    src = (
        "int f(int x) {\n"
        "    if (x > 0) { x = 1; }\n"
        "    else if (x < 0) { x = 2; }\n"
        "    else { x = 3; }\n"
        "    switch (x) { case 1: x = 10; break; default: x = 0; break; }\n"
        "    int last = x;\n"
        "    return last;\n"
        "}\n"
    )
    ast = _ast(src)
    fn = ast.declarations[0]
    _start, end = LexicalScopeIndex.body_range(fn.body, fn.line)
    assert end >= 7  # the deepest statement (return last) is on line 7 (1-based)


def test_resolve_variable_type_inferred_constructor_call():
    # On the pre-analysis AST the `var` has no annotated type, so resolution
    # falls to the constructor-call inference branch.
    src = "class T { public int v; public T() { self.v = 0; } }\nint main() { var t = T(); return t.v; }\n"
    ct = analyze(src).analyzed.class_table
    assert RESOLVER.resolve_variable_type("t", _ast(src), ct) == "T"


def test_resolve_variable_type_inferred_new_expr():
    src = "class T { public int v; public T() { self.v = 0; } }\nint main() { var t = new T(); return t.v; }\n"
    ct = analyze(src).analyzed.class_table
    assert RESOLVER.resolve_variable_type("t", _ast(src), ct) == "T"


def test_resolve_variable_type_in_else_branch():
    src = (
        "class T { public int v; public T() { self.v = 0; } }\n"
        "int main() {\n"
        "    if (1) { return 0; }\n"
        "    else { T made = new T(); return made.v; }\n"
        "}\n"
    )
    a = analyze(src)
    assert RESOLVER.resolve_variable_type("made", a.ast, a.analyzed.class_table) == "T"


def test_resolve_variable_type_in_else_if_branch():
    src = (
        "class T { public int v; public T() { self.v = 0; } }\n"
        "int main() {\n"
        "    if (1) { return 0; }\n"
        "    else if (0) { T made = new T(); return made.v; }\n"
        "    return 1;\n"
        "}\n"
    )
    a = analyze(src)
    assert RESOLVER.resolve_variable_type("made", a.ast, a.analyzed.class_table) == "T"


def test_resolve_chain_static_root():
    src = (
        "class A { public int v; public A() { self.v = 0; }\n"
        "          public int go() { return 1; } }\n"
        "int main() { A a = A(); return a.go(); }\n"
    )
    a = analyze(src)
    pos = pos_of(src, "A a")
    a_idx = next(
        i for i, t in enumerate(a.tokens) if t.value == "A" and t.line == pos.line + 1 and t.col == pos.character + 1
    )
    assert RESOLVER.resolve_chain_type(a, a.tokens, a_idx, a.analyzed.class_table) == "A"


def test_resolve_chain_broken_hop_is_none():
    src = "class A { public int v; public A() { self.v = 0; } }\nint main() { A a = A(); return a.bad; }\n"
    a = analyze(src)
    bad_idx = next(i for i, t in enumerate(a.tokens) if t.value == "bad")
    assert RESOLVER.resolve_chain_type(a, a.tokens, bad_idx, a.analyzed.class_table) is None
