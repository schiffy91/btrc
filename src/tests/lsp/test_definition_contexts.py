"""Go-to-definition for variables declared in every statement context (the
definition-side mirror of the hover scan), plus rich enums, structs, typedefs."""

from src.tests.lsp.lsphelp import analyze, get_definition, pos_of

SRC = """\
import std.{vector, map};

int run(int n) {
    Vector<int> items = [1, 2, 3];
    for x in items {
        int y = x + 1;
    }
    parallel for z in items {
        int w = z + 1;
    }
    Map<string, int> m = {};
    for k, v in m {
        int u = v + 1;
    }
    try {
        int a = 1;
    } catch (err) {
        int b = 2;
    }
    if (n > 0) {
        int p = 1;
    } else if (n < 0) {
        int q = 2;
    }
    switch (n) {
        case 1: { int c1 = 1; } break;
        default: break;
    }
    return 0;
}
"""


def _def(needle, occurrence=1, offset=0):
    return get_definition(analyze(SRC), pos_of(SRC, needle, occurrence, offset))


def test_clean():
    assert analyze(SRC).diagnostics == []


def test_def_forin_var():
    assert _def("x + 1", offset=0) is not None


def test_def_parallel_for_var():
    assert _def("z + 1", offset=0) is not None


def test_def_map_value_var():
    assert _def("v + 1", offset=0) is not None


def test_def_catch_var():
    assert _def("catch (err)", offset=7) is not None


def test_def_var_in_elseif():
    assert _def("int q = 2", offset=4) is not None


def test_def_var_in_switch_case():
    assert _def("int c1 = 1", offset=4) is not None


# --- rich enum / struct / typedef definitions ---

DECLS = """\
enum class Shape { Circle(int r), Square(int s) }

struct Pt { int x; int y; };

typedef int Id;

int main() {
    Id n = 5;
    return n;
}
"""


def test_def_typedef_usage_resolves_to_decl():
    loc = get_definition(analyze(DECLS), pos_of(DECLS, "Id n", offset=0))
    assert loc is not None and loc.range.start.line == 4  # `typedef int Id;`
