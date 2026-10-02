"""Hover across symbol kinds: field, local variable, parameter, method, class,
and documented keywords. Asserts the hover text names the symbol/type."""

from src.tests.lsp.lsphelp import SAMPLE, analyze, get_document_symbols, get_hover_info, hover_text, pos_of


def _hov(needle, occurrence=1, offset=1):
    return hover_text(get_hover_info(analyze(SAMPLE), pos_of(SAMPLE, needle, occurrence, offset)))


def test_hover_field_member():
    # `self.x` inside getX → field x of type int
    t = _hov("self.x", occurrence=2, offset=5)
    assert "x" in t and "int" in t


def test_hover_method_member():
    t = _hov("p.getX", offset=2)
    assert "getX" in t


def test_hover_local_variable():
    # `p` in `p.getX()` is a local of type Point
    t = _hov("p.getX", offset=0)
    assert "Point" in t


def test_hover_local_int_variable():
    # the `v` in `return v;`
    t = _hov("return v", offset=7)
    assert "v" in t or "int" in t


def test_hover_parameter():
    # `a` in `return a + b;` is a parameter of add
    t = _hov("a + b", offset=0)
    assert "a" in t


def test_hover_class_name():
    t = _hov("Point p", offset=1)
    assert "Point" in t


def test_hover_documented_keyword():
    # `public` is in the keyword-docs table
    t = _hov("public int x", offset=0)
    assert t != ""


def test_hover_none_on_operator():
    assert get_hover_info(analyze(SAMPLE), pos_of(SAMPLE, " + ", offset=1)) is None


def test_hover_none_without_tokens():
    # empty/whitespace document → no tokens → no hover
    from src.tests.lsp.lsphelp import analyze as a

    r = a("   \n")
    assert get_hover_info(r, pos_of("   \n", " ", offset=0)) is None


def test_hover_inside_fstring_interpolation():
    source = """\
int main() {
    string label = "Name";
    string command = f"printf {label} >&2";
    return 0;
}
"""
    t = hover_text(get_hover_info(analyze(source), pos_of(source, "{label}", offset=2)))

    assert "string" in t and "label" in t


def test_hover_method_parameter():
    src = (
        "class C { public int v; public C(int v) { self.v = v; }\n"
        "          public int f(int a) { return a; } }\n"
        "int main() { C c = C(1); return c.f(2); }\n"
    )
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "return a", offset=7)))
    assert "a" in t


def test_hover_builtin_string_member():
    src = 'int main() { string s = "hi"; int n = s.len(); return n; }\n'
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "s.len", offset=2)))
    assert "len" in t


def test_hover_member_on_unresolved_receiver_is_none():
    src = (
        "class Point { public int x; public Point() { self.x = 0; }\n"
        "              public int getX() { return self.x; } }\n"
        "int main() { return mystery.getX(); }\n"
    )
    assert get_hover_info(analyze(src), pos_of(src, "mystery.getX", offset=8)) is None


def test_hover_unknown_member_returns_none():
    src = (
        "class B { public int b; public B() { self.b = 0; }\n"
        "          public int getB() { return self.b; } }\n"
        "class D extends B { public int d; public D() { self.d = 0; } }\n"
        "int main() { D x = new D(); return x.nope(); }\n"
    )
    assert get_hover_info(analyze(src), pos_of(src, "x.nope", offset=2)) is None


def test_hover_in_body_non_variable_identifier_is_none():
    src = "class K { public int v; public K() { self.v = 0; } }\nint main() { K k = K(); return foobar; }\n"
    assert get_hover_info(analyze(src), pos_of(src, "return foobar", offset=7)) is None


def test_unnamed_prototype_parameters_list_by_type_in_symbols():
    source = "int external(int, char*);\nint main(void) { return external(1, null); }\n"
    result = analyze(source)
    details = {symbol.name: symbol.detail for symbol in get_document_symbols(result)}
    assert details["external"] == "int(int, char*)"
    assert details["main"] == "int()"
    assert hover_text(get_hover_info(result, pos_of(source, "external(1", offset=1))) is not None
