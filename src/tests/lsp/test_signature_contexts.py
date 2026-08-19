"""Signature help: inherited-method parent chain, active-parameter counting
that ignores commas inside string literals, and builtin function calls."""

from src.tests.lsp.lsphelp import get_signature_help
from src.tests.lsp.lsphelp import analyze, pos_of


def _sig(src, needle, occurrence=1, offset=0):
    return get_signature_help(analyze(src), pos_of(src, needle, occurrence, offset))


def test_inherited_method_signature_walks_parent_chain():
    src = (
        "class Base {\n"
        "    public int b;\n"
        "    public Base() { self.b = 0; }\n"
        "    public int combine(int a, int c) { return a + c; }\n"
        "}\n"
        "class Sub extends Base { public Sub() { self.b = 1; } }\n"
        "int main() { Sub s = Sub(); return s.combine(1, 2); }\n"
    )
    s = _sig(src, "s.combine(1", offset=10)  # cursor in the first argument
    assert s is not None and "combine" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 2


def test_active_parameter_ignores_commas_in_strings():
    src = 'int two(string a, int b) { return b; }\nint main() { return two("x, y", 3); }\n'
    s = _sig(src, ", 3)", offset=2)  # cursor on the real second arg
    assert s is not None and s.active_parameter == 1


def test_builtin_function_call_signature_no_crash():
    src = 'int main() { print("hello"); return 0; }\n'
    s = _sig(src, 'print("hello"', offset=6)
    assert s is None or s.signatures  # whatever it returns, it must not crash
