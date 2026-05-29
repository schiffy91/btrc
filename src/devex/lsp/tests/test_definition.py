"""Go-to-definition (cmd-click): resolve a use to its declaration for every
symbol kind — class, function, method, field, local, parameter, enum value."""

from src.devex.lsp.definition import get_definition
from src.devex.lsp.tests.lsphelp import analyze, pos_of

SRC = """\
enum Color { RED, GREEN, BLUE };

int add(int a, int b) { return a + b; }

class Point {
    public int x;
    public Point(int x) { self.x = x; }
    public int getX() { return self.x; }
    public int doubled() { return add(self.x, self.x); }
}

int main() {
    Point p = Point(5);
    int v = p.getX();
    Color c = RED;
    return v;
}
"""


def _def_line(needle, occurrence=1, offset=1):
    r = analyze(SRC)
    loc = get_definition(r, pos_of(SRC, needle, occurrence, offset))
    return loc.range.start.line if loc else None


def test_class_type_use_resolves_to_class_decl():
    # `Point p` on line 12 → class Point on line 4
    assert _def_line("Point p") == 4


def test_method_call_resolves_to_method_decl():
    # `p.getX()` on line 13 → getX method on line 7
    assert _def_line("p.getX", offset=2) == 7


def test_local_variable_resolves_to_its_declaration():
    # `p` in `p.getX()` (line 13) → `Point p = ...` declaration on line 12
    assert _def_line("p.getX", offset=0) == 12


def test_function_call_resolves_to_function_decl():
    # `add(...)` inside doubled() (line 8) → `int add(...)` on line 2
    assert _def_line("add(self.x", offset=0) == 2


def test_field_access_resolves_to_field_decl():
    # `self.x` in getX (line 7) → field `public int x` on line 5
    assert _def_line("self.x", occurrence=2, offset=5) == 5


def test_enum_value_resolves_to_enum_decl():
    # `RED` in `Color c = RED` (line 14) → enum on line 0
    assert _def_line("= RED", offset=2) == 0


def test_no_definition_on_keyword():
    r = analyze(SRC)
    # cursor on the `return` keyword (line 15) has no definition
    assert get_definition(r, pos_of(SRC, "return v", offset=0)) is None
