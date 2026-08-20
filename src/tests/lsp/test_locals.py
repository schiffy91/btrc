"""Locals declared inside control-flow blocks (for/if/else/while) — exercises
the statement-scanning variable resolution shared by hover, definition, and
completion (_check_stmt_for_var / _collect_vars_in_stmt / _scan_for_var_type)."""

from src.tests.lsp.lsphelp import analyze, get_completions, get_definition, get_hover_info, hover_text, pos_of

SRC = """\
class Widget {
    public int w;
    public Widget(int w) { self.w = w; }
    public int area() { return self.w * self.w; }
}

int compute(int n) {
    int total = 0;
    for (int i = 0; i < n; i = i + 1) {
        Widget item = Widget(i);
        int a = item.area();
        if (a > 10) {
            int big = a + a;
            total = total + big;
        } else {
            int small = a;
            total = total + small;
        }
    }
    int j = 0;
    while (j < n) {
        var step = j + 1;
        j = step;
    }
    return total;
}

int main() {
    return compute(5);
}
"""


def _hov(needle, occurrence=1, offset=0):
    return hover_text(get_hover_info(analyze(SRC), pos_of(SRC, needle, occurrence, offset)))


def _def_line(needle, occurrence=1, offset=0):
    loc = get_definition(analyze(SRC), pos_of(SRC, needle, occurrence, offset))
    return loc.range.start.line if loc else None


def test_clean():
    assert analyze(SRC).diagnostics == []


def test_hover_class_typed_local_in_for_block():
    assert "Widget" in _hov("item.area", offset=0)


def test_definition_class_typed_local_in_for_block():
    assert _def_line("item.area", offset=0) == 9


def test_completion_on_local_in_for_block():
    names = {i.label for i in get_completions(analyze(SRC), pos_of(SRC, "item.area", offset=5))}
    assert {"area", "w"} <= names


def test_hover_int_local_from_method_return():
    # `a` = item.area() → int
    assert "int" in _hov("a + a", offset=0)


def test_definition_int_local_in_for_block():
    assert _def_line("a + a", offset=0) == 10


def test_definition_local_in_if_block():
    # `big` declared inside the if-block
    assert _def_line("total + big", offset=8) == 12


def test_definition_local_in_else_block():
    # `small` declared inside the else-block
    assert _def_line("total + small", offset=8) == 15


def test_definition_var_inferred_in_while_block():
    # `step` is `var step = j + 1` inside the while-block
    assert _def_line("j = step", offset=4) == 21
