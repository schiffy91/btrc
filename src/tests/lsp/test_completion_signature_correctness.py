"""Regressions for completion/signature lexical and scope correctness."""

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp.analysis.resolution import LexicalScopeIndex
from src.tests.lsp.lsphelp import analyze, get_completions, get_signature_help, pos_of


def _labels(source: str, needle: str, offset: int) -> set[str]:
    result = analyze(source)
    return {item.label for item in get_completions(result, pos_of(source, needle, offset=offset))}


def test_nested_self_completion_uses_deepest_method_extent():
    source = """\
class Counter {
    public int number;
    public Counter() { self.number = 0; }
    public void update(bool ready) {
        if (ready) {
            while (ready) {
                self.number = 1;
            }
        }
    }
}
"""
    labels = _labels(source, "self.number = 1", len("self."))
    assert "number" in labels


def test_partial_member_spelling_keeps_member_completion_context():
    source = (
        "class Counter { public int number; "
        "public Counter() { self.number = 0; } }\n"
        "int main() { Counter c = Counter(); return c.num; }\n"
    )
    assert "number" in _labels(source, "c.num", len("c.num"))


def test_general_keywords_follow_grammar_and_skip_unimplemented_reservations():
    source = "int main() { ret }\n"
    labels = _labels(source, "ret", len("ret"))
    assert {"finally", "import", "interface"} <= labels
    assert {"goto", "override"}.isdisjoint(labels)


def test_static_completion_honors_access_mode_and_live_class_shadowing():
    source = (
        "class Math { public int value; public Math() { self.value = 0; } "
        "public int local() { return self.value; } "
        "class int helper(int x) { return x; } }\n"
        "int main() { return Math.he; }\n"
    )
    labels = _labels(source, "Math.he", len("Math."))
    assert "helper" in labels
    assert {"value", "local", "abs"}.isdisjoint(labels)


def test_local_named_like_class_resolves_as_instance_receiver():
    source = (
        "class Box { public int x; public Box() { self.x = 0; } }\n"
        "class Holder { public int y; public Holder() { self.y = 0; } "
        "public int read() { Box Holder = Box(); return Holder.x; } }\n"
    )
    labels = _labels(source, "Holder.x", len("Holder."))
    assert "x" in labels
    assert "y" not in labels


def test_completion_includes_properties_and_separates_static_fields():
    source = (
        "class Box { public int raw; class int total; "
        "public Box() { self.raw = 0; } "
        "public int value { get { return self.raw; } } }\n"
        "int main() { Box box = Box(); return box.value + Box.total; }\n"
    )
    instance_labels = _labels(source, "box.value", len("box."))
    static_labels = _labels(source, "Box.total", len("Box."))
    assert "value" in instance_labels
    assert "total" not in instance_labels
    assert "total" in static_labels
    assert "value" not in static_labels


def test_completion_resolves_type_through_property_chain():
    source = (
        "class Inner { public int number; public Inner() { self.number = 0; } }\n"
        "class Outer { public Inner inner { get { return Inner(); } } "
        "public Outer() {} }\n"
        "int main() { Outer outer = Outer(); return outer.inner.num; }\n"
    )
    labels = _labels(source, "outer.inner.num", len("outer.inner.num"))
    assert "number" in labels


def test_static_call_chain_rejects_instance_methods_and_follows_class_methods():
    source = (
        "class Box { public int number; public Box() { self.number = 0; } }\n"
        "class Factory { public Factory() {} "
        "public Box instance() { return Box(); } "
        "class Box make() { return Box(); } }\n"
        "int main() { return Factory.instance().num + Factory.make().num; }\n"
    )
    invalid = _labels(source, "Factory.instance().num", len("Factory.instance()."))
    valid = _labels(source, "Factory.make().num", len("Factory.make()."))
    assert invalid == set()
    assert "number" in valid


def test_fstring_member_call_has_signature_help():
    source = (
        "class C { public C() {} public int add(int x) { return x; } }\n"
        'int main() { C c = C(); print(f"{c.add(1)}"); return 0; }\n'
    )
    signature = get_signature_help(
        analyze(source),
        pos_of(source, "c.add(1)", offset=len("c.add(")),
    )
    assert signature is not None
    assert "add" in signature.signatures[0].label


def test_parenthesis_text_inside_string_is_not_a_call():
    source = 'int add(int x) { return x; }\nint main() { string text = "add("; return 0; }\n'
    signature = get_signature_help(
        analyze(source),
        pos_of(source, '"add(', offset=len('"add(')),
    )
    assert signature is None


def test_collection_commas_do_not_advance_active_parameter():
    source = (
        "import Library.Vector;\n"
        "int choose(Vector<int> values, int fallback, int extra) { return fallback; }\n"
        "int main() { return choose([1, 2], 3, 4); }\n"
    )
    signature = get_signature_help(
        analyze(source),
        pos_of(source, "], 3", offset=len("], 3")),
    )
    assert signature is not None
    assert signature.active_parameter == 1


def test_user_class_shadows_generated_static_signature_metadata():
    source = "class Math { public Math() {} public int local() { return 0; } }\nint main() { return Math.abs(1); }\n"
    signature = get_signature_help(
        analyze(source),
        pos_of(source, "Math.abs(1)", offset=len("Math.abs(")),
    )
    assert signature is None


def test_source_scope_matching_ignores_braces_inside_strings():
    source = """\
class A {
    public string marker;
    public A() { self.marker = "}"; }
    public int later() { return 1; }
}
"""
    ast = Parser(Lexer(source, "scope.btrc").tokenize()).parse()
    assert LexicalScopeIndex.find_enclosing_class_from_source(ast, source, 3) == "A"
    assert LexicalScopeIndex.find_closing_brace_line(source.splitlines(), 0) == 4


def test_completion_user_class_static_methods():
    src = (
        "class Util {\n"
        "    public int x;\n"
        "    public Util() { self.x = 0; }\n"
        "    class int helper(int a) { return a; }\n"
        "}\n"
        "int main() { return Util.helper(5); }\n"
    )
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Util.helper", offset=5))}
    assert "helper" in names


def test_completion_static_methods_after_stdlib_class():
    src = 'import Library.Strings;\nint main() { string s = Strings.repeat("a", 2); return 0; }\n'
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Strings.repeat", offset=8))}
    assert "repeat" in names


def test_completion_after_stdlib_class_name():
    src = "import Library.Math;\nint main() { int x = Math.abs(-3); return x; }\n"
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Math.abs", offset=5))}
    assert names  # Math.* static methods offered


def test_completion_stdlib_class_dedup():
    # Strings is both in the analyzed class_table and the stdlib static table;
    # the dedup loop avoids duplicate labels.
    src = 'import Library.Strings;\nint main() { string s = Strings.copy("x"); return 0; }\n'
    items = get_completions(analyze(src), pos_of(src, "Strings.copy", offset=8))
    labels = [i.label for i in items]
    assert len(labels) == len(set(labels))  # no duplicates


def test_completion_user_class_shadowing_stdlib_has_no_instance_leak():
    src = (
        "class Math { public int v; public Math() { self.v = 0; }\n"
        "             public int sq() { return self.v * self.v; } }\n"
        "int main() { int r = Math.sq(); return r; }\n"
    )
    items = get_completions(analyze(src), pos_of(src, "Math.sq", offset=5))
    assert items == []


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


def test_completion_chain_with_unresolved_head_is_empty():
    src = "int main() { return ghost.inner.value; }\n"
    items = get_completions(analyze(src), pos_of(src, "ghost.inner.value", offset=12))
    assert items == []


def test_completion_member_of_enum_typed_field_is_empty():
    # b.c resolves to the enum type Color, which is neither a built-in nor a
    # class -> _members_for_type returns no members.
    src = (
        "enum Color { RED, GREEN };\n"
        "class Box { public Color c; public Box() { self.c = RED; } }\n"
        "int main() { Box b = Box(); return b.c.zz; }\n"
    )
    items = get_completions(analyze(src), pos_of(src, "b.c.zz", offset=4))
    assert items == []
