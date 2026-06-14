"""Exact identifier resolution via the analyzer occurrence table.

These tests drive the real LSP features through the same front-end the server
uses and assert that go-to-definition, find-references, and hover use exact
analyzer-truth resolution (the occurrence table) rather than token heuristics.
"""

from src.devex.lsp.definition import get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.occurrences import (
    build_index,
    occurrence_at,
    references_to,
)
from src.devex.lsp.references import get_references
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of


def _def_pos(loc):
    return None if loc is None else (loc.range.start.line, loc.range.start.character)


def _ref_positions(source, position):
    refs = get_references(analyze(source), position)
    return sorted((r.range.start.line, r.range.start.character) for r in refs)


# --------------------------------------------------------- exact go-to-def

LOCALS = """\
int add(int a, int b) {
    int sum = a + b;
    return sum;
}
"""


def test_occurrence_recorded_for_local_use():
    r = analyze(LOCALS)
    occ = occurrence_at(r, pos_of(LOCALS, "return sum", offset=7))
    assert occ is not None
    assert occ.kind == "variable" and occ.name == "sum"
    assert (occ.def_line, occ.def_col) == (2, 9)  # 'int sum =' name token (1-based)


def test_goto_def_local_via_occurrence():
    r = analyze(LOCALS)
    loc = get_definition(r, pos_of(LOCALS, "return sum", offset=7))
    assert _def_pos(loc) == (1, 8)  # 0-based 'sum' in the declaration


def test_goto_def_param_via_occurrence():
    r = analyze(LOCALS)
    occ = occurrence_at(r, pos_of(LOCALS, "a + b", offset=0))
    assert occ is not None and occ.kind == "param" and occ.name == "a"
    loc = get_definition(r, pos_of(LOCALS, "a + b", offset=0))
    assert _def_pos(loc) == (0, 12)  # the 'a' parameter name


LOOPVAR = """\
int main() {
    for x in range(10) {
        int y = x + 1;
    }
    return 0;
}
"""


def test_goto_def_loop_var_via_occurrence():
    r = analyze(LOOPVAR)
    occ = occurrence_at(r, pos_of(LOOPVAR, "x + 1", offset=0))
    assert occ is not None and occ.kind == "loop" and occ.name == "x"
    # The loop var resolves to its own loop header (definition is exact-by-site).
    loc = get_definition(r, pos_of(LOOPVAR, "x + 1", offset=0))
    assert loc is not None and loc.range.start.line == 1


SAMPLE_CLASS = """\
class Point {
    public int x;
    public Point(int px) { self.x = px; }
    public int getX() { return self.x; }
}

int main() {
    Point p = Point(5);
    return p.getX();
}
"""


def test_goto_def_field_member_access():
    r = analyze(SAMPLE_CLASS)
    # self.x in getX -> the field declaration line (index 1).
    loc = get_definition(r, pos_of(SAMPLE_CLASS, "return self.x", offset=12))
    assert loc is not None and loc.range.start.line == 1


def test_goto_def_method_member_access():
    r = analyze(SAMPLE_CLASS)
    # p.getX() -> the method declaration line (index 3).
    loc = get_definition(r, pos_of(SAMPLE_CLASS, "p.getX", offset=3))
    assert loc is not None and loc.range.start.line == 3


# -------------------------------------------------- references group by def site

SIBLINGS = """\
int first() {
    int total = 1;
    return total;
}

int second() {
    int total = 99;
    return total;
}
"""


def test_references_group_by_def_site_first():
    # The 'total' in first() must not pull in second()'s same-named local.
    refs = _ref_positions(SIBLINGS, pos_of(SIBLINGS, "return total", 1, offset=7))
    assert refs == [(1, 8), (2, 11)]


def test_references_group_by_def_site_second():
    refs = _ref_positions(SIBLINGS, pos_of(SIBLINGS, "return total", 2, offset=7))
    assert refs == [(6, 8), (7, 11)]


def test_references_to_helper_uses_occurrence_def_site():
    r = analyze(SIBLINGS)
    occ = occurrence_at(r, pos_of(SIBLINGS, "return total", 1, offset=7))
    assert occ is not None
    positions = references_to(r, (occ.def_file, occ.def_line, occ.def_col))
    # Only the use site in first() is a recorded occurrence (decl is added by
    # the reference finder, not the occurrence table).
    assert positions == [(3, 12)]


# ------------------------------------------------------------ hover inferred var

INFERRED = """\
int main() {
    var nums = [1, 2, 3];
    var name = "hi";
    return 0;
}
"""


def test_hover_shows_inferred_vector_type():
    r = analyze(INFERRED)
    text = hover_text(get_hover_info(r, pos_of(INFERRED, "nums", offset=1)))
    assert "Vector<int>" in text
    assert "Local variable" in text


def test_hover_shows_inferred_string_type():
    r = analyze(INFERRED)
    text = hover_text(get_hover_info(r, pos_of(INFERRED, "name", offset=1)))
    assert "string" in text


# --------------------------------------------------------------- index plumbing

def test_index_cached_per_snapshot():
    r = analyze(LOCALS)
    a = build_index(r)
    b = build_index(r)
    assert a is b  # cached in result._caches


def test_no_occurrence_outside_resolution():
    # A bare unknown identifier the analyzer never resolves has no occurrence.
    src = "int main() { return missing; }\n"
    r = analyze(src)
    assert occurrence_at(r, pos_of(src, "missing", offset=1)) is None
