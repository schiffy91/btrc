"""Hover on variables declared in every statement context — C-for init, for-in
loop var, parallel-for var, catch var, else-if block, switch case — plus type
inference from constructor and `new` initializers."""

from src.tests.lsp.lsphelp import analyze, get_hover_info, hover_text, pos_of

SRC = """\
import std.vector;

class Box { public int v; public Box(int v) { self.v = v; } }
Box make(int v) { return Box(v); }

int run(int n) {
    for (int i = 0; i < n; i = i + 1) {
        int sq = i * i;
    }
    Vector<int> items = [1, 2, 3];
    for x in items {
        int y = x + 1;
    }
    parallel for z in items {
        int w = z + 1;
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
        default: { int cd = 0; } break;
    }
    Box bx = make(5);
    var nb = new Box(7);
    return 0;
}
"""


def _hov(needle, occurrence=1, offset=0):
    return hover_text(get_hover_info(analyze(SRC), pos_of(SRC, needle, occurrence, offset)))


def test_hover_cfor_init_variable():
    assert "i" in _hov("i * i", offset=0)


def test_hover_forin_loop_variable():
    assert _hov("x + 1", offset=0) != ""  # for-in loop var x


def test_hover_parallel_for_variable():
    assert _hov("z + 1", offset=0) != ""  # parallel-for var z


def test_hover_catch_variable():
    assert _hov("catch (err)", offset=7) != ""  # the catch var `err`


def test_hover_var_in_elseif_block():
    assert "q" in _hov("int q = 2", offset=4)  # declared inside else-if


def test_hover_var_in_switch_case():
    assert "c1" in _hov("int c1 = 1", offset=4)  # declared inside a case


def test_hover_var_type_from_constructor_call():
    assert "Box" in _hov("bx = make", offset=0)  # _infer_var_type via CallExpr


def test_hover_var_type_from_new_expr():
    assert "Box" in _hov("nb = new", offset=0)  # _infer_var_type via NewExpr
