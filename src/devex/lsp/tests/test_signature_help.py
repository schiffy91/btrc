"""Signature help: function calls (with active-parameter tracking), constructor
calls, member-method calls, and `new` expressions."""

from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import SAMPLE, analyze, pos_of


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
    assert len(s.signatures[0].parameters) == 1   # the ctor's int x


def test_member_method_call_signature():
    # cursor inside p.getX()  — getX takes no parameters
    s = _sig(SAMPLE, "p.getX()", offset=7)
    assert s is not None
    assert "getX" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 0


def test_new_expression_signature():
    src = ("class Box { public int v; public Box(int v) { self.v = v; } }\n"
           "int main() { Box b = new Box(9); return b.v; }\n")
    s = _sig(src, "new Box(9)", offset=8)   # cursor inside (9)
    assert s is not None
    assert "Box" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 1


def test_no_signature_outside_call():
    s = get_signature_help(analyze(SAMPLE), pos_of(SAMPLE, "return v", offset=0))
    assert s is None
