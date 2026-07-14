"""Hover across symbol kinds: field, local variable, parameter, method, class,
and documented keywords. Asserts the hover text names the symbol/type."""

from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.tests.lsphelp import SAMPLE, analyze, hover_text, pos_of


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
    from src.devex.lsp.tests.lsphelp import analyze as a

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
