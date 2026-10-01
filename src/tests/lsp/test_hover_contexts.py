"""Hover on variables declared in every statement context — C-for init, for-in
loop var, parallel-for var, catch var, else-if block, switch case — plus type
inference from constructor and `new` initializers."""

from src.tests.lsp.lsphelp import analyze, get_hover_info, hover_text, pos_of

SRC = """\
import Library.Vector;

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


def test_hover_variable_declared_in_try_block():
    src = "int main() {\n    try { int caught = 5; return caught; }\n    catch (string e) { return 0; }\n}\n"
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "return caught", offset=7)))
    assert "caught" in t


def test_hover_variable_declared_in_else_block():
    src = "int main() {\n    if (1) { return 1; }\n    else { int picked = 2; return picked; }\n}\n"
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "return picked", offset=7)))
    assert "picked" in t


def test_hover_var_inferred_from_unknown_call():
    # the callee is undefined → the analyzer can't infer the type, so the
    # hover heuristic falls back to the callee name.
    src = "int main() { var thing = mystery(); return 0; }\n"
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "var thing", offset=4)))
    assert "thing" in t or "mystery" in t


# ---- variables nested inside block bodies (hover returns from inner scan) ---

BLOCKS = """\
import Library.{Vector, Map};

int run(int n) {
    Vector<int> items = [1, 2, 3];
    Map<string, int> m = {};
    for k, v in m {
        int kv = v;
    }
    for x in items {
        int inFor = x;
    }
    parallel for z in items {
        int inPar = z;
    }
    if (n > 0) {
        int inThen = 1;
    } else {
        int inElse = 2;
    }
    while (n > 0) {
        int inWhile = n;
        n = n - 1;
    }
    var fromCall = make(3);
    var fromNew = new Holder(4);
    return 0;
}

class Holder { public int h; public Holder(int h) { self.h = h; } }
Holder make(int v) { return Holder(v); }
"""


def _hb(needle, offset=0):
    return hover_text(get_hover_info(analyze(BLOCKS), pos_of(BLOCKS, needle, offset=offset)))


def test_hover_var_in_for_body():
    assert _hb("int inFor", offset=4) != ""


def test_hover_var_in_parallel_body():
    assert _hb("int inPar", offset=4) != ""


def test_hover_var_in_then_block():
    assert _hb("int inThen", offset=4) != ""


def test_hover_var_in_while_body():
    assert _hb("int inWhile", offset=4) != ""


def test_hover_forin_second_loop_variable():
    assert _hb("k, v in m", offset=3) != ""  # the second loop var (var_name2)


def test_hover_var_inferred_from_call():
    assert "Holder" in _hb("fromCall", offset=0)
