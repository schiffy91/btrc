"""Behavioral tests for the remaining LSP features: hover, completion,
find-references, rename, document symbols, signature help, semantic tokens.
All drive the real feature functions through the shared compiler, over SAMPLE
and over sources that exercise struct, typedef, enum and generic declarations."""

from lsprotocol import types as lsp

from src.tests.lsp.lsphelp import (
    SAMPLE,
    analyze,
    decoded_semantic_tokens,
    get_completions,
    get_document_symbols,
    get_hover_info,
    get_references,
    get_rename_edits,
    get_semantic_tokens,
    get_signature_help,
    hover_text,
    pos_of,
    prepare_rename,
)

# ----------------------------------------------------------------- hover


def test_hover_method_shows_name():
    r = analyze(SAMPLE)
    txt = hover_text(get_hover_info(r, pos_of(SAMPLE, "p.getX", offset=2)))
    assert "getX" in txt


def test_hover_class_shows_name():
    r = analyze(SAMPLE)
    txt = hover_text(get_hover_info(r, pos_of(SAMPLE, "Point p", offset=1)))
    assert "Point" in txt


def test_hover_empty_on_blank():
    r = analyze(SAMPLE)
    # column far past end of an empty line → no hover
    assert get_hover_info(r, pos_of(SAMPLE, "\n\n", offset=1)) is None


# ------------------------------------------------------------- completion


def test_member_completion_lists_methods():
    r = analyze(SAMPLE)
    # cursor right after `p.` in `p.getX()` → member completion on Point
    items = get_completions(r, pos_of(SAMPLE, "p.getX", offset=2))
    labels = {it.label for it in items}
    assert "getX" in labels and "doubled" in labels


def test_top_level_completion_includes_user_symbols():
    r = analyze(SAMPLE)
    # inside main(), at the start of the `return` line, identifiers are offered
    items = get_completions(r, pos_of(SAMPLE, "return v", offset=0))
    labels = {it.label for it in items}
    assert "Point" in labels or "add" in labels


# ------------------------------------------------- references + rename


def test_find_references_of_method():
    r = analyze(SAMPLE)
    refs = get_references(r, pos_of(SAMPLE, "p.getX", offset=2), include_declaration=True)
    lines = sorted(loc.range.start.line for loc in refs)
    assert 7 in lines  # the getX declaration
    assert 13 in lines  # the p.getX() call


def test_find_references_excludes_declaration_when_asked():
    r = analyze(SAMPLE)
    with_decl = get_references(r, pos_of(SAMPLE, "p.getX", offset=2), include_declaration=True)
    without = get_references(r, pos_of(SAMPLE, "p.getX", offset=2), include_declaration=False)
    assert len(without) < len(with_decl)


def test_prepare_rename_returns_symbol_range():
    r = analyze(SAMPLE)
    rng = prepare_rename(r, pos_of(SAMPLE, "p = Point", offset=0))  # the local `p`
    assert rng is not None
    assert rng.start.line == 12


def test_rename_local_edits_all_uses():
    r = analyze(SAMPLE)
    edit = get_rename_edits(r, pos_of(SAMPLE, "p = Point", offset=0), "q")
    assert edit is not None
    # gather edits regardless of changes vs documentChanges representation
    changes = edit.changes or {}
    all_edits = [e for edits in changes.values() for e in edits]
    if not all_edits and edit.document_changes:
        for dc in edit.document_changes:
            all_edits.extend(getattr(dc, "edits", []))
    assert len(all_edits) >= 2  # decl + use
    assert all(e.new_text == "q" for e in all_edits)


# --------------------------------------------------------- doc symbols


def test_document_symbols_tree():
    r = analyze(SAMPLE)
    syms = get_document_symbols(r)
    names = {s.name for s in syms}
    assert {"Point", "main", "add", "Color"} <= names
    point = next(s for s in syms if s.name == "Point")
    child_names = {c.name for c in (point.children or [])}
    assert "getX" in child_names and "x" in child_names


# ------------------------------------------------------ signature help


def test_signature_help_inside_call():
    r = analyze(SAMPLE)
    # inside add(self.x, self.x) on line 8 — cursor just after the '('
    sig = get_signature_help(r, pos_of(SAMPLE, "add(self.x", offset=4))
    assert sig is not None and sig.signatures
    assert "add" in sig.signatures[0].label


# ------------------------------------------------------ semantic tokens


def test_semantic_tokens_nonempty():
    r = analyze(SAMPLE)
    toks = get_semantic_tokens(r)
    assert toks is not None
    assert len(toks.data) > 0 and len(toks.data) % 5 == 0  # 5 ints per token


def test_semantic_tokens_cover_fstring_variables_in_document_only():
    source = 'int main() { string label = "hi"; var command = f"printf {label} >&2"; return 0; }\n'

    tokens = get_semantic_tokens(analyze(source))

    assert tokens is not None
    decoded = decoded_semantic_tokens(source, tokens.data, with_position=True)
    assert (0, 58, "label", "variable", 0) in decoded


def test_semantic_tokens_classify_type_names():
    src = (
        "struct Pt { int x; int y; };\n"
        "typedef int Id;\n"
        "class Widget { public int w; public Widget() { self.w = 0; } }\n"
        "int main() {\n"
        "    Widget wd = Widget();\n"
        "    Id n = 5;\n"
        "    return n + wd.w;\n"
        "}\n"
    )
    toks = get_semantic_tokens(analyze(src))
    assert toks is not None and len(toks.data) > 0


def test_semantic_tokens_new_constructor_and_generic():
    src = (
        "enum Color { RED, GREEN };\n"
        "class Box<T> { public T v; public Box(T v) { self.v = v; } }\n"
        "int main() {\n"
        "    Box<int> b = new Box(5);\n"
        "    Color c = RED;\n"
        "    return 0;\n"
        "}\n"
    )
    toks = get_semantic_tokens(analyze(src))
    assert toks is not None and len(toks.data) > 0
    decoded = decoded_semantic_tokens(src, toks.data)
    assert ("Box", "type", 0) in decoded
    assert ("Color", "type", 0) in decoded
    assert ("RED", "enumMember", 0) in decoded


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


def test_semantic_tokens_present_for_struct_generic():
    toks = get_semantic_tokens(analyze(GEN))
    assert toks is not None and toks.data


# ------------------------------- struct / typedef / enum / generic declarations

# Source exercising struct / typedef / generic class / inheritance.
TYPES = """\
struct Pt { int x; int y; };

typedef int MyInt;

enum Color { RED, BLUE };

class Base {
    public int b;
    public Base() { self.b = 0; }
    public int describe() { return self.b; }
}

class Gen<T> extends Base {
    public T val;
    public Gen(T v) { self.val = v; }
    public T get() { return self.val; }
}

int main() {
    Base base = Base();
    int d = base.describe();
    MyInt alias = 3;
    Color color = RED;
    return d + alias;
}
"""


def test_semantic_tokens_struct_generic_typedef():
    toks = get_semantic_tokens(analyze(TYPES))
    assert toks is not None and toks.data
    decoded = decoded_semantic_tokens(TYPES, toks.data)
    assert ("MyInt", "type", 0) in decoded
    assert ("RED", "enumMember", 0) in decoded


def test_document_symbols_struct_typedef_generic():
    names = {s.name for s in get_document_symbols(analyze(TYPES))}
    assert {"Pt", "MyInt", "Color", "Gen", "Base"} <= names


UNIONS = """\
union Number { int integer; float real; };
typedef union { int code; } Status;
struct Point { int x; };
int main() { return 0; }
"""


def test_document_symbols_union_is_a_struct_symbol_with_its_members():
    """LSP has no union kind: a union is a Struct symbol whose detail says union (C row 9)."""
    symbols = {s.name: s for s in get_document_symbols(analyze(UNIONS))}
    for name, members in (("Number", ["integer", "real"]), ("Status", ["code"])):
        assert symbols[name].kind == lsp.SymbolKind.Struct
        assert symbols[name].detail == "union"
        assert [child.name for child in symbols[name].children] == members
    assert symbols["Point"].kind == lsp.SymbolKind.Struct
    assert not symbols["Point"].detail
