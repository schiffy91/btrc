"""Scope-aware variable navigation: references/rename anchored to the
innermost visible definition (real brace-matched block ends), f-string
reference sites, stdlib rename protection, and caret-at-word-end lookup."""

from src.devex.lsp.definition import DefinitionMap, get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references, get_rename_edits, prepare_rename
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of
from src.devex.lsp.utils import body_range, find_matching_brace_line


def _edits(source, position, new_name="renamed"):
    edit = get_rename_edits(analyze(source), position, new_name)
    if edit is None:
        return None
    return {
        uri: sorted((e.range.start.line, e.range.start.character) for e in edits)
        for uri, edits in (edit.changes or {}).items()
    }


def _ref_positions(source, position):
    refs = get_references(analyze(source), position)
    return sorted((r.range.start.line, r.range.start.character) for r in refs)


# --------------------------------------------------------------- sibling scopes

SIBLINGS = """\
int first() {
    int x = 1;
    return x;
}

int second() {
    int x = 2;
    return x;
}
"""


def test_rename_local_does_not_touch_sibling_function():
    edits = _edits(SIBLINGS, pos_of(SIBLINGS, "return x", occurrence=1, offset=7), "y")
    assert edits is not None
    (positions,) = edits.values()
    assert positions == [(1, 8), (2, 11)]  # first()'s decl + use only


def test_references_local_stay_in_declaring_function():
    refs = _ref_positions(SIBLINGS, pos_of(SIBLINGS, "return x", occurrence=2, offset=7))
    assert refs == [(6, 8), (7, 11)]  # second()'s decl + use only


def test_rename_parameter_does_not_touch_sibling_function():
    src = "int add(int a, int b) { return a + b; }\nint mul(int a, int b) { return a * b; }\n"
    edits = _edits(src, pos_of(src, "a + b", offset=0), "left")
    assert edits is not None
    (positions,) = edits.values()
    assert positions == [(0, 12), (0, 31)]  # add()'s param + use, mul() untouched


# ------------------------------------------------------------------- shadowing

SHADOW = """\
int f(int n) {
    int v = 1;
    if (n > 0) {
        int v = 2;
        n = v;
    }
    return v;
}
"""


def test_shadowing_inner_use_resolves_to_inner_decl():
    loc = get_definition(analyze(SHADOW), pos_of(SHADOW, "n = v", offset=4))
    assert loc is not None and loc.range.start.line == 3


def test_shadowing_use_after_block_resolves_to_outer_decl():
    loc = get_definition(analyze(SHADOW), pos_of(SHADOW, "return v", offset=7))
    assert loc is not None and loc.range.start.line == 1


def test_rename_inner_shadow_leaves_outer_untouched():
    edits = _edits(SHADOW, pos_of(SHADOW, "n = v", offset=4), "w")
    assert edits is not None
    (positions,) = edits.values()
    assert positions == [(3, 12), (4, 12)]  # inner decl + inner use only


def test_rename_outer_leaves_inner_shadow_untouched():
    edits = _edits(SHADOW, pos_of(SHADOW, "return v", offset=7), "w")
    assert edits is not None
    (positions,) = edits.values()
    assert positions == [(1, 8), (6, 11)]  # outer decl + return use only


def test_param_shadowed_by_local():
    src = "int f(int v) {\n    int v = 2;\n    return v;\n}\n"
    loc = get_definition(analyze(src), pos_of(src, "return v", offset=7))
    assert loc is not None and loc.range.start.line == 1  # the local, not the param


# ------------------------------------------------------------------- loop vars

LOOPS = """\
int run(int n) {
    int total = 0;
    for (int i = 0; i < n; i = i + 1) {
        total = total + i;
    }
    for (int i = 0; i < n; i = i + 1) {
        total = total - i;
    }
    return total;
}
"""


def test_loop_var_references_confined_to_its_loop():
    refs = _ref_positions(LOOPS, pos_of(LOOPS, "total + i", offset=8))
    assert refs and all(2 <= line <= 4 for line, _col in refs)
    assert (3, 24) in refs  # the body use


def test_rename_loop_var_does_not_touch_sibling_loop():
    edits = _edits(LOOPS, pos_of(LOOPS, "total + i", offset=8), "j")
    assert edits is not None
    (positions,) = edits.values()
    assert all(2 <= line <= 4 for line, _col in positions)
    assert len(positions) == 5  # decl, cond, incr (x2), body use


# ------------------------------------------------------------------- catch var

CATCH = """\
int safe(int n) {
    try {
        throw "bad";
    } catch (err) {
        return n;
    }
    return err;
}
"""


def test_catch_var_definition_inside_catch_block():
    loc = get_definition(analyze(CATCH), pos_of(CATCH, "catch (err)", offset=7))
    assert loc is not None and loc.range.start.line == 3


def test_catch_var_confined_to_catch_block():
    # `err` after the catch block is out of scope: no definition, no hover.
    r = analyze(CATCH)
    pos = pos_of(CATCH, "return err", offset=7)
    assert get_definition(r, pos) is None
    assert get_hover_info(r, pos) is None


def test_catch_var_references_exclude_out_of_scope_use():
    refs = _ref_positions(CATCH, pos_of(CATCH, "catch (err)", offset=7))
    assert (3, 13) in refs
    assert (6, 11) not in refs  # the out-of-scope `return err`


# -------------------------------------------------------------- use before decl


def test_use_before_decl_excluded_from_references_and_rename():
    src = "int f() {\n    int y = w;\n    int w = 5;\n    return w;\n}\n"
    refs = _ref_positions(src, pos_of(src, "return w", offset=7))
    assert (1, 12) not in refs  # the use-before-decl `= w`
    assert (2, 8) in refs and (3, 11) in refs
    edits = _edits(src, pos_of(src, "return w", offset=7), "z")
    (positions,) = edits.values()
    assert (1, 12) not in positions


# -------------------------------------------------------------------- f-strings

FSTR = """\
int main() {
    string v = "x";
    string s = f"hello {v} bye";
    return 0;
}
"""


def test_fstring_interpolation_included_in_references():
    refs = _ref_positions(FSTR, pos_of(FSTR, "string v", offset=7))
    line = 2
    col = FSTR.split("\n")[line].index("{v}") + 1
    assert (line, col) in refs


def test_fstring_member_access_included_in_member_references():
    # member-access adjacency works on the expanded navigation stream
    src = (
        "class P { public int x; public P(int x) { self.x = x; }\n"
        "          public int getX() { return self.x; } }\n"
        'int main() { P p = P(1); string s = f"val {p.getX()}"; return 0; }\n'
    )
    refs = _ref_positions(src, pos_of(src, "public int getX", offset=11))
    col = src.split("\n")[2].index("p.getX") + 2
    assert (2, col) in refs


def test_fstring_interpolation_included_in_rename():
    edits = _edits(FSTR, pos_of(FSTR, "string v", offset=7), "name")
    assert edits is not None
    (positions,) = edits.values()
    col = FSTR.split("\n")[2].index("{v}") + 1
    assert (2, col) in positions and (1, 11) in positions


# -------------------------------------------------------------- rename refusals


def test_rename_refused_on_unresolvable_identifier():
    src = "int main() { return ghost; }\n"
    pos = pos_of(src, "ghost", offset=1)
    assert get_rename_edits(analyze(src), pos, "spirit") is None
    assert prepare_rename(analyze(src), pos) is None


STDLIB_USE = """\
import std.vector;

int main() {
    Vector<int> v = [1, 2, 3];
    v.push(4);
    return v.len();
}
"""


def test_rename_refused_on_stdlib_member():
    pos = pos_of(STDLIB_USE, "v.push", offset=2)
    assert get_rename_edits(analyze(STDLIB_USE), pos, "append") is None
    assert prepare_rename(analyze(STDLIB_USE), pos) is None


def test_rename_refused_on_stdlib_class():
    pos = pos_of(STDLIB_USE, "Vector<int>", offset=0)
    assert get_rename_edits(analyze(STDLIB_USE), pos, "Vec") is None


def test_references_still_list_stdlib_definition_site():
    refs = get_references(analyze(STDLIB_USE), pos_of(STDLIB_USE, "v.push", offset=2))
    assert any("/stdlib/" in r.uri for r in refs)  # the def site is listed...
    assert any(r.uri.endswith("/t.btrc") for r in refs)  # ...alongside the use


def test_rename_local_with_stdlib_type_still_works():
    edits = _edits(STDLIB_USE, pos_of(STDLIB_USE, "v.push", offset=0), "items")
    assert edits is not None
    (positions,) = edits.values()
    assert len(positions) == 3  # decl, v.push, v.len


# ------------------------------------------------------------ scope ends (real)

NEIGHBOR = """\
int a() {
    int data = 1;
    return data;
}

int b() {
    return data;
}
"""


def test_undeclared_name_does_not_resolve_to_neighbor_local():
    r = analyze(NEIGHBOR)
    pos = pos_of(NEIGHBOR, "return data", occurrence=2, offset=7)
    assert get_definition(r, pos) is None


def test_hover_does_not_leak_after_function_end():
    r = analyze(NEIGHBOR)
    pos = pos_of(NEIGHBOR, "return data", occurrence=2, offset=7)
    assert get_hover_info(r, pos) is None


def test_block_local_invisible_after_block_ends():
    src = "int f(int n) {\n    if (n > 0) {\n        int inner = 1;\n    }\n    return inner;\n}\n"
    r = analyze(src)
    pos = pos_of(src, "return inner", offset=7)
    assert get_definition(r, pos) is None
    assert get_hover_info(r, pos) is None


def test_body_range_uses_real_block_end():
    src = "void f() { }\nint g() {\n    int q = 1;\n    return q;\n}\nint main() { return 0; }\n"
    r = analyze(src)
    decls = [d for d in r.ast.declarations if getattr(d, "name", None) in ("f", "g")]
    f = next(d for d in decls if d.name == "f")
    g = next(d for d in decls if d.name == "g")
    assert body_range(f.body, f.line, r.tokens) == (1, 1)  # empty body, no +1000 slop
    assert body_range(g.body, g.line, r.tokens) == (2, 5)  # real closing brace line


def test_find_matching_brace_line_token_space():
    src = 'int f() {\n    string s = "}}}{";\n    return 0;\n}\n'
    r = analyze(src)
    # Braces inside string literals are not tokens: the match is exact.
    assert find_matching_brace_line(r.tokens, 1, 9) == 4


# ------------------------------------------------------------ caret at word end


def test_hover_at_caret_immediately_after_identifier():
    src = "int main() { int count = 5; return count; }\n"
    pos = pos_of(src, "return count", offset=12)  # caret right after the final `t`
    t = hover_text(get_hover_info(analyze(src), pos))
    assert "count" in t and "int" in t


def test_definition_at_caret_immediately_after_identifier():
    src = "int main() { int count = 5; return count; }\n"
    loc = get_definition(analyze(src), pos_of(src, "return count", offset=12))
    assert loc is not None and loc.range.start.character == 17


# ----------------------------------------------------------- find_var_def picks


def test_find_var_def_innermost_and_def_site_identity():
    r = analyze(SHADOW)
    dmap = DefinitionMap.from_result(r)
    inner_use = dmap.find_var_def("v", 5, 13)  # `n = v` (1-based 5)
    outer_use = dmap.find_var_def("v", 7, 12)  # `return v`
    assert inner_use is not None and inner_use.line == 4  # 1-based decl lines
    assert outer_use is not None and outer_use.line == 2
    # the definition's own name token anchors itself
    assert dmap.find_var_def("v", inner_use.line, inner_use.col) is inner_use
