"""Signature help: function calls (with active-parameter tracking), constructor
calls, member-method calls, `new` expressions, calls that resolve to nothing,
and the call-context scanning helpers."""

from lsprotocol import types as lsp

from src.tests.lsp.lsphelp import CATALOG, SAMPLE, analyze, get_signature_help, pos_of
from src.tests.lsp.lsphelp import SIGNATURE_HELP as sighelp


def _sig(source, needle, occurrence=1, offset=0):
    return get_signature_help(analyze(source), pos_of(source, needle, occurrence, offset))


def test_function_call_first_parameter_active():
    # cursor on the first argument of add(self.x, self.x)
    s = _sig(SAMPLE, "add(self.x", offset=4)
    assert s is not None
    assert "add" in s.signatures[0].label
    assert s.active_parameter == 0
    assert len(s.signatures[0].parameters) == 2


def test_function_call_second_parameter_active():
    # cursor inside the second argument (4th occurrence of self.x)
    s = _sig(SAMPLE, "self.x", occurrence=4, offset=1)
    assert s is not None and "add" in s.signatures[0].label
    assert s.active_parameter == 1


def test_constructor_call_signature():
    # cursor inside Point(5)
    s = _sig(SAMPLE, "Point(5)", offset=6)
    assert s is not None
    assert "Point" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 1  # the ctor's int x


def test_member_method_call_signature():
    # cursor inside p.getX()  — getX takes no parameters
    s = _sig(SAMPLE, "p.getX()", offset=7)
    assert s is not None
    assert "getX" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 0


def test_new_expression_signature():
    src = (
        "class Box { public int v; public Box(int v) { self.v = v; } }\n"
        "int main() { Box b = new Box(9); return b.v; }\n"
    )
    s = _sig(src, "new Box(9)", offset=8)  # cursor inside (9)
    assert s is not None
    assert "Box" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 1


def test_no_signature_outside_call():
    s = get_signature_help(analyze(SAMPLE), pos_of(SAMPLE, "return v", offset=0))
    assert s is None


def test_constructor_signature_with_params():
    src = (
        "class Vec { public int a; public int b;\n"
        "    public Vec(int a, int b) { self.a = a; self.b = b; } }\n"
        "int main() { Vec v = Vec(1, 2); return v.a; }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "Vec(1, 2)", offset=4))
    assert s is not None and len(s.signatures[0].parameters) == 2


def test_signature_constructorless_class_offers_empty_params():
    src = "class Empty { public int v; }\nint main() { Empty e = Empty(); return 0; }\n"
    s = get_signature_help(analyze(src), pos_of(src, "Empty()", offset=6))
    assert s is not None and s.signatures[0].parameters == []


def test_signature_zero_arguments_active_param_zero():
    src = (
        "class C { public int v; public C() { self.v = 0; }\n"
        "          public int f(int a) { return a; } }\n"
        "int main() { C c = C(); return c.f(); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "c.f()", offset=4))  # cursor between ( )
    assert s is None or s.active_parameter == 0


def test_signature_help_outside_any_call_is_none():
    src = "int main() { int z = 1 + 2; return z; }\n"
    assert get_signature_help(analyze(src), pos_of(src, "1 + 2", offset=0)) is None


def test_find_call_context_paren_after_operator_is_none():
    src = "int main() { int z = 2 * (3 + 4); return z; }\n"
    assert get_signature_help(analyze(src), pos_of(src, "(3 + 4)", offset=1)) is None


def test_signature_unknown_function_call_is_none():
    src = "int main() { return mystery(1); }\n"
    assert get_signature_help(analyze(src), pos_of(src, "mystery(1)", offset=8)) is None


def test_signature_new_unknown_class_is_none():
    src = "int main() { var z = new Nope(1); return 0; }\n"
    assert get_signature_help(analyze(src), pos_of(src, "new Nope(1)", offset=9)) is None


def test_stdlib_signature_unknown_method_is_none():
    assert CATALOG.static_signature("Math", "definitely_not_a_method") is None


# ---- call-context scanning helpers -----------------------------------------


def test_count_active_parameter_without_enclosing_paren():
    # No open paren before the cursor: the scan falls off the buffer start and
    # returns the commas counted at depth 0.
    assert sighelp._count_active_parameter("a, b", lsp.Position(line=0, character=4)) == 1


def test_count_active_parameter_out_of_range_position():
    assert sighelp._count_active_parameter("f(x)", lsp.Position(line=9, character=0)) == 0


def test_find_call_context_out_of_range_position_is_none():
    assert sighelp._find_call_context("f(x)", lsp.Position(line=9, character=0)) is None
