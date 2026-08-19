"""Regressions for completion/signature lexical and scope correctness."""

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.devex.lsp.analysis.resolution import LexicalScopeIndex
from src.tests.lsp.lsphelp import get_completions
from src.tests.lsp.lsphelp import get_signature_help
from src.tests.lsp.lsphelp import analyze, pos_of


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
        'int main() { C c = C(); println(f"{c.add(1)}"); return 0; }\n'
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
        "import std.vector;\n"
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
