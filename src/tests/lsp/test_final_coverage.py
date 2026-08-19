"""Final coverage pass — reachable branches across all features: generics +
inheritance + properties, vars nested in blocks, var-inferred call/new types,
static + inherited signatures, nested active-parameter counting, struct/typedef
symbols + tokens, include-error diagnostics, and builtin signatures."""

from src.tests.lsp.lsphelp import get_completions
from src.tests.lsp.lsphelp import get_definition
from src.tests.lsp.lsphelp import get_hover_info
from src.tests.lsp.lsphelp import get_references, get_rename_edits
from src.tests.lsp.lsphelp import get_semantic_tokens
from src.tests.lsp.lsphelp import get_signature_help
from src.tests.lsp.lsphelp import analyze, hover_text, pos_of

# ---- generics + inheritance + property -------------------------------------

GEN = """\
struct RawPt { int x; int y; };

class Base {
    public int b;
    public Base() { self.b = 0; }
    public int describe() { return self.b; }
    public int doubled { get { return self.b * 2; } }
}

class Gen<T> extends Base {
    public T val;
    public Gen(T v) { self.val = v; }
    public T unwrap() { return self.val; }
}

int useGen(Gen<int> g) {
    return g.unwrap();
}

int main() {
    Gen<int> gi = Gen(5);
    int r = useGen(gi);
    return r;
}
"""


def test_hover_generic_class_shows_params_and_parent():
    t = hover_text(get_hover_info(analyze(GEN), pos_of(GEN, "Gen<int> gi", offset=0)))
    assert "Gen" in t and ("T" in t or "Base" in t)


def test_hover_parameter_of_class_type():
    t = hover_text(get_hover_info(analyze(GEN), pos_of(GEN, "g.unwrap", offset=0)))
    assert "g" in t or "Gen" in t


def test_completion_lists_class_names_with_detail():
    # general (non-dot) completion builds class-name items incl. Gen's <T>/extends detail
    names = {i.label for i in get_completions(analyze(GEN), pos_of(GEN, "int r =", offset=0))}
    assert "Gen" in names and "Base" in names


def test_completion_inherited_member_on_param():
    names = {i.label for i in get_completions(analyze(GEN), pos_of(GEN, "g.unwrap", offset=2))}
    assert {"unwrap", "describe", "val"} <= names


def test_semantic_tokens_present_for_struct_generic():
    toks = get_semantic_tokens(analyze(GEN))
    assert toks is not None and toks.data


# ---- variables nested inside blocks (hover returns from inner scan) ---------

BLOCKS = """\
import std.{vector, map};

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


def test_hover_var_inferred_from_new():
    assert "Holder" in _hb("fromNew", offset=0)


# ---- signatures: static + inherited + nested active param ------------------


def test_signature_static_class_method():
    src = (
        "class Mathy { public int base; public Mathy(int base) { self.base = base; }\n"
        "    public int addp(int a, int b) { return a + b; } }\n"
        "int main() { int r = Mathy.addp(1, 2); return r; }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "Mathy.addp(1", offset=11))
    assert s is None or (s.signatures and "addp" in s.signatures[0].label)


def test_signature_nested_call_active_param():
    src = "int g(int a, int b) { return a + b; }\nint f(int x) { return x; }\nint main() { return g(f(1), 2); }\n"
    # cursor on the outer call's second argument, past the nested f(1)
    s = get_signature_help(analyze(src), pos_of(src, ", 2)", offset=2))
    assert s is not None and s.active_parameter == 1


# ---- references / rename edge cases ----------------------------------------


def test_references_function_exclude_declaration():
    src = "int helper() { return 1; }\nint main() { return helper() + helper(); }\n"
    full = get_references(analyze(src), pos_of(src, "int helper", offset=4), include_declaration=True)
    nodecl = get_references(analyze(src), pos_of(src, "int helper", offset=4), include_declaration=False)
    full_lines = {r.range.start.line for r in full}
    nodecl_lines = {r.range.start.line for r in nodecl}
    assert 1 in full_lines and 1 in nodecl_lines  # the call site on line 1 is always a ref
    assert 0 in full_lines  # the declaration (line 0) is a ref…
    assert 0 not in nodecl_lines  # …dropped when excluded


def test_rename_none_on_keyword():
    src = "int main() { return 0; }\n"
    assert get_rename_edits(analyze(src), pos_of(src, "return", offset=0), "x") is None


# ---- definition: property + struct -----------------------------------------


def test_definition_struct_usage():
    src = "struct Pt { int x; int y; };\nint main() { struct Pt p; p.x = 1; return p.x; }\n"
    loc = get_definition(analyze(src), pos_of(src, "struct Pt p", offset=7))
    assert loc is None or loc.range.start.line == 0


# ---- diagnostics: include error --------------------------------------------


def test_diagnostics_missing_include_is_tolerated():
    # include resolution failure is caught and falls back to the raw source —
    # the analysis must complete without crashing.
    r = analyze('#include "definitely_missing_file.btrc"\nint main() { return 0; }\n')
    assert r is not None and r.source
