"""Direct contract tests for the shared resolution helpers in utils.py."""

from lsprotocol import types as lsp

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.tests.lsphelp import analyze
from src.devex.lsp.utils import (
    body_range,
    find_closing_brace_line,
    find_enclosing_class,
    find_enclosing_class_from_source,
    find_token_index,
    get_text_before_cursor,
    resolve_member_type,
    resolve_variable_type,
    type_repr,
)

_CHAIN = (
    "class Inner { public int v; public Inner(int v) { self.v = v; }\n"
    "              public int get() { return self.v; } }\n"
    "class Outer { public Inner inner; public Outer() { self.inner = Inner(1); }\n"
    "              public Inner make() { return self.inner; } }\n"
    "int main() { Outer o = Outer(); return o.make().get(); }\n"
)


def test_resolve_member_type_field_method_builtin_unknown():
    ct = analyze(_CHAIN).analyzed.class_table
    assert resolve_member_type("Outer", "inner", ct) == "Inner"   # field type
    assert resolve_member_type("Outer", "make", ct) == "Inner"    # method return type
    assert resolve_member_type("string", "len", ct) is not None   # builtin member
    assert resolve_member_type("Nope", "x", ct) is None           # unknown owner
    assert resolve_member_type("Outer", "ghost", ct) is None      # member not found


def test_resolve_variable_type_decl_forms():
    src = ("class Box { public int v; public Box(int v) { self.v = v; } }\n"
           "Box mk() { return Box(1); }\n"
           "int run(Box p) { var a = Box(2); var b = new Box(3); var c = mk(); return 0; }\n")
    r = analyze(src)
    ast, ct = r.ast, r.analyzed.class_table
    assert resolve_variable_type("a", ast, ct) == "Box"   # constructor call
    assert resolve_variable_type("b", ast, ct) == "Box"   # new expression
    assert resolve_variable_type("p", ast, ct) == "Box"   # parameter type


def test_type_repr_none_is_void():
    assert type_repr(None) == "void"
    assert type_repr(TypeExpr(base="int")) == "int"
    assert type_repr(
        TypeExpr(
            base="Map",
            generic_args=[TypeExpr(base="string"), TypeExpr(base="int")],
            pointer_depth=1,
            is_const=True,
            is_nullable=True,
        )
    ) == "const Map<string, int>*?"


def test_find_token_index_missing_returns_none():
    r = analyze("int main() { return 0; }\n")
    fake = Token(type=TokenType.IDENT, value="nope", line=999, col=1)
    assert find_token_index(r.tokens, fake) is None


def test_get_text_before_cursor_out_of_range():
    assert get_text_before_cursor("a\nb\n", lsp.Position(line=99, character=0)) == ""


def test_find_closing_brace_line_match_and_unbalanced():
    assert find_closing_brace_line(["class X {", "    int y;", "}"], 0) == 2
    assert find_closing_brace_line(["class X {", "    int y;"], 0) is None


def test_find_enclosing_class_inside_outside_and_none():
    src = ("class A {\n"
           "    public int m() { return 1; }\n"
           "}\n"
           "int top() { return 0; }\n")
    r = analyze(src)
    assert find_enclosing_class(r.ast, 2) == "A"     # 1-based line inside A
    assert find_enclosing_class(r.ast, 4) is None    # top() is not in a class
    assert find_enclosing_class(None, 1) is None


def test_find_enclosing_class_from_source_inside_outside_and_none():
    src = "class A {\n    public int m() { return 1; }\n}\n"
    r = analyze(src)
    assert find_enclosing_class_from_source(r.ast, src, 1) == "A"   # 0-based
    assert find_enclosing_class_from_source(r.ast, src, 3) is None
    assert find_enclosing_class_from_source(None, "", 0) is None


def test_body_range_empty_body_uses_fallback():
    r = analyze("void f() { }\nint main() { return 0; }\n")
    fn = r.ast.declarations[0]
    start, end = body_range(fn.body, fn.line)
    assert end - start >= 1000   # empty body → wide fallback range


def test_body_range_walks_elseif_and_switch():
    src = ("int f(int x) {\n"
           "    if (x > 0) { x = 1; }\n"
           "    else if (x < 0) { x = 2; }\n"
           "    else { x = 3; }\n"
           "    switch (x) { case 1: x = 10; break; default: x = 0; break; }\n"
           "    int last = x;\n"
           "    return last;\n"
           "}\n")
    r = analyze(src)
    fn = r.ast.declarations[0]
    _start, end = body_range(fn.body, fn.line)
    assert end >= 7   # the deepest statement (return last) is on line 7 (1-based)
