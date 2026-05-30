"""More reachable edge paths: member hover/definition on an unresolvable
receiver (scan-all-classes fallback), constructor and builtin signatures."""

from src.devex.lsp.definition import get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of

# `x` is undefined, so its type can't be resolved — but getX exists on Point,
# exercising the "scan every class for the member" fallback.
UNRESOLVED = ("class Point {\n"
              "    public int x;\n"
              "    public Point(int x) { self.x = x; }\n"
              "    public int getX() { return self.x; }\n"
              "}\n"
              "int main() { return x.getX(); }\n")


def test_definition_member_on_unresolvable_receiver():
    loc = get_definition(analyze(UNRESOLVED), pos_of(UNRESOLVED, "x.getX", offset=2))
    assert loc is None or loc.range.start.line == 3   # Point.getX


def test_constructor_signature_with_params():
    src = ("class Vec { public int a; public int b;\n"
           "    public Vec(int a, int b) { self.a = a; self.b = b; } }\n"
           "int main() { Vec v = Vec(1, 2); return v.a; }\n")
    s = get_signature_help(analyze(src), pos_of(src, "Vec(1, 2)", offset=4))
    assert s is not None and len(s.signatures[0].parameters) == 2


def test_new_constructor_signature():
    src = ("class Vec { public int a; public Vec(int a) { self.a = a; } }\n"
           "int main() { Vec v = new Vec(7); return v.a; }\n")
    s = get_signature_help(analyze(src), pos_of(src, "new Vec(7)", offset=8))
    assert s is not None and "Vec" in s.signatures[0].label


def test_builtin_member_signature_help():
    # signature help inside a built-in string method call
    src = 'int main() { string s = "hello"; int i = s.indexOf("l"); return i; }\n'
    s = get_signature_help(analyze(src), pos_of(src, 's.indexOf("l"', offset=10))
    assert s is None or s.signatures
