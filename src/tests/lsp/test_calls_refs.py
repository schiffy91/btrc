"""Member-method signature help (with parameters + nesting), and references /
rename for classes, functions, methods, and fields: declaration exclusion,
static receivers, and rename refusal on keywords, literals, and built-ins."""

from src.tests.lsp.lsphelp import analyze, get_references, get_rename_edits, get_signature_help, pos_of, prepare_rename

SRC = """\
class Calc {
    public int base;
    public Calc(int base) { self.base = base; }
    public int addTwo(int a, int b) { return self.base + a + b; }
}

int twice(int x) { return x * 2; }

int main() {
    Calc c = Calc(10);
    int r = c.addTwo(1, 2);
    int n = twice(twice(3));
    return r + n;
}
"""


def _sig(needle, occurrence=1, offset=0):
    return get_signature_help(analyze(SRC), pos_of(SRC, needle, occurrence, offset))


def _ref_lines(needle, occurrence=1, offset=1):
    refs = get_references(analyze(SRC), pos_of(SRC, needle, occurrence, offset))
    return {r.range.start.line for r in refs}


def test_clean():
    assert analyze(SRC).diagnostics == []


def test_member_method_signature_with_params_first_active():
    s = _sig("c.addTwo(1", offset=9)  # cursor on the first argument
    assert s is not None and "addTwo" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 2
    assert s.active_parameter == 0


def test_member_method_signature_second_active():
    s = _sig(", 2)", offset=2)  # cursor on the second argument
    assert s is not None and s.active_parameter == 1


def test_nested_call_inner_signature():
    # cursor on the 3 inside the inner twice(3)
    s = _sig("twice(3)", offset=6)
    assert s is not None and "twice" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 1


def test_references_of_class():
    # Calc: declaration (line 0) + `Calc c = Calc(10)` (line 9, twice)
    assert {0, 9} <= _ref_lines("class Calc", offset=6)


def test_references_of_function():
    # twice: declaration (line 6) + two uses on line 11
    assert {6, 11} <= _ref_lines("int twice", offset=4)


def test_prepare_rename_on_method():
    rng = prepare_rename(analyze(SRC), pos_of(SRC, "public int addTwo", offset=11))
    assert rng is not None and rng.start.line == 3


def test_rename_method_edits_decl_and_call():
    edit = get_rename_edits(analyze(SRC), pos_of(SRC, "public int addTwo", offset=11), "sum")
    assert edit is not None
    changes = edit.changes or {}
    all_edits = [e for edits in changes.values() for e in edits]
    if not all_edits and edit.document_changes:
        for dc in edit.document_changes:
            all_edits.extend(getattr(dc, "edits", []))
    lines = {e.range.start.line for e in all_edits}
    assert {3, 10} <= lines  # method decl + the call site
    assert all(e.new_text == "sum" for e in all_edits)


def test_stdlib_static_method_signature():
    # signature help inside a stdlib static-method call (Strings.repeat)
    src = 'import Library.Strings;\nint main() { string s = Strings.repeat("ab", 3); return s.len() > 0 ? 0 : 1; }\n'
    s = get_signature_help(analyze(src), pos_of(src, 'repeat("ab"', offset=7))
    assert s is not None and s.signatures


def test_prepare_rename_none_on_literal():
    src = "int main() { return 42; }\n"
    assert prepare_rename(analyze(src), pos_of(src, "42", offset=0)) is None


def test_rename_none_on_keyword():
    src = "int main() { return 0; }\n"
    assert get_rename_edits(analyze(src), pos_of(src, "return", offset=0), "x") is None


def test_prepare_rename_builtin_generic_keyword_is_none():
    # `List` lexes as an identifier but is a reserved built-in name.
    src = "int main() { List<int> xs = new List<int>(); return 0; }\n"
    assert prepare_rename(analyze(src), pos_of(src, "List<int> xs", offset=0)) is None


# ---- references: include_declaration=False ---------------------------------


def test_references_function_exclude_declaration():
    src = "int helper() { return 1; }\nint main() { return helper() + helper(); }\n"
    full = get_references(analyze(src), pos_of(src, "int helper", offset=4), include_declaration=True)
    nodecl = get_references(analyze(src), pos_of(src, "int helper", offset=4), include_declaration=False)
    full_lines = {r.range.start.line for r in full}
    nodecl_lines = {r.range.start.line for r in nodecl}
    assert 1 in full_lines and 1 in nodecl_lines  # the call site on line 1 is always a ref
    assert 0 in full_lines  # the declaration (line 0) is a ref…
    assert 0 not in nodecl_lines  # …dropped when excluded


def test_class_references_can_exclude_declaration():
    src = (
        "class Widget { public int v; public Widget() { self.v = 0; } }\n"
        "int main() { Widget w = new Widget(); return w.v; }\n"
    )
    pos = pos_of(src, "Widget w", offset=0)  # type usage -> classified as a class
    with_decl = get_references(analyze(src), pos, include_declaration=True)
    without = get_references(analyze(src), pos, include_declaration=False)
    assert len(without) == len(with_decl) - 1


def test_member_references_can_exclude_declaration():
    src = (
        "class P { public int val; public P() { self.val = 0; }\n"
        "          public int read() { return self.val; } }\n"
        "int main() { P p = P(); return p.val; }\n"
    )
    decl_pos = pos_of(src, "public int val", offset=11)
    with_decl = get_references(analyze(src), decl_pos, include_declaration=True)
    without = get_references(analyze(src), decl_pos, include_declaration=False)
    assert len(without) == len(with_decl) - 1


def test_member_references_resolve_static_and_skip_unresolved_receivers():
    src = (
        "class Klass { public int v; public Klass() { self.v = 0; }\n"
        "              public int m() { return 1; } }\n"
        "int main() { Klass k = Klass(); int a = k.m();"
        " int b = Klass.m(); int c = ghost.m(); return a; }\n"
    )
    refs = get_references(analyze(src), pos_of(src, "public int m", offset=11), include_declaration=True)
    assert len(refs) == 3
