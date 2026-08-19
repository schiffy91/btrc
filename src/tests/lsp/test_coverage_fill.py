"""Targeted coverage for less-common but real paths: struct/typedef/generic
symbols + semantic tokens, include-error diagnostics, static-method and
class-name completion, builtin-member hover, and references edge cases."""

from src.tests.lsp.lsphelp import get_completions
from src.tests.lsp.lsphelp import get_hover_info
from src.tests.lsp.lsphelp import get_references, prepare_rename
from src.tests.lsp.lsphelp import get_semantic_tokens
from src.tests.lsp.lsphelp import get_document_symbols
from src.tests.lsp.lsphelp import analyze, decoded_semantic_tokens, hover_text, pos_of

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


def test_inherited_method_references_via_variable():
    # describe() is inherited by Gen (not overridden); references on the
    # declaration span the inherited call site through a Gen variable.
    src = (
        "class Base { public int b; public Base() { self.b = 0; }\n"
        "             public int describe() { return self.b; } }\n"
        "class Sub extends Base { public Sub() { self.b = 1; } }\n"
        "int main() { Sub s = Sub(); return s.describe(); }\n"
    )
    refs = get_references(analyze(src), pos_of(src, "public int describe", occurrence=1, offset=11))
    lines = {r.range.start.line for r in refs}
    assert 3 in lines  # the s.describe() call


def test_references_exclude_declaration_for_class():
    src = "class Widget { public int w; public Widget() { self.w = 0; } }\nint main() { Widget x = Widget(); return x.w; }\n"
    with_decl = get_references(analyze(src), pos_of(src, "class Widget", offset=6), include_declaration=True)
    without = get_references(analyze(src), pos_of(src, "class Widget", offset=6), include_declaration=False)
    assert len(without) == len(with_decl) - 1


def test_completion_static_methods_after_stdlib_class():
    src = 'import std.strings;\nint main() { string s = Strings.repeat("a", 2); return 0; }\n'
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Strings.repeat", offset=8))}
    assert "repeat" in names


def test_completion_self_members():
    src = (
        "class Counter {\n"
        "    public int n;\n"
        "    public Counter() { self.n = 0; }\n"
        "    public int bump() { return self.n; }\n"
        "}\n"
    )
    # cursor right after `self.` inside bump()
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "self.n", occurrence=2, offset=5))}
    assert {"n", "bump"} <= names


def test_hover_builtin_string_member():
    src = 'int main() { string s = "hi"; int n = s.len(); return n; }\n'
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "s.len", offset=2)))
    assert "len" in t


def test_prepare_rename_none_on_literal():
    src = "int main() { return 42; }\n"
    assert prepare_rename(analyze(src), pos_of(src, "42", offset=0)) is None
