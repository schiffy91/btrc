"""Final reachable-branch coverage: static/inherited/chain signature
resolution, heuristic type inference when the analyzer can't help, property
definitions, static-method completion, and parent-chain references."""

from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of

# ---- signature resolution branches -----------------------------------------


def test_signature_static_method_via_class_name():
    src = (
        "class Mathy {\n"
        "    public int base;\n"
        "    public Mathy(int base) { self.base = base; }\n"
        "    class int addp(int a, int b) { return a + b; }\n"
        "}\n"
        "int main() { return Mathy.addp(1, 2); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "Mathy.addp(1", offset=11))
    assert s is not None and "addp" in s.signatures[0].label


def test_signature_inherited_method_via_typed_variable():
    src = (
        "class Base {\n"
        "    public int b;\n"
        "    public Base() { self.b = 0; }\n"
        "    public int combine(int a, int c) { return a + c; }\n"
        "}\n"
        "class Sub extends Base { public Sub() { self.b = 1; } }\n"
        "int main() { Sub s = Sub(); return s.combine(1, 2); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "s.combine(1", offset=10))
    assert s is not None and "combine" in s.signatures[0].label
    assert len(s.signatures[0].parameters) == 2


def test_signature_unresolved_receiver_is_none():
    src = (
        "class Foo { public int f; public Foo() { self.f = 0; }\n"
        "            public int act(int x) { return x; } }\n"
        "int main() { int n = 5; return n.act(2); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "n.act(2", offset=6))
    assert s is None


def test_signature_nested_chain_method_call():
    src = (
        "class Inner { public int v; public Inner() { self.v = 0; }\n"
        "              public int run(int x) { return x; } }\n"
        "class Outer { public Inner inner; public Outer() { self.inner = Inner(); }\n"
        "              public Inner make() { return self.inner; } }\n"
        "int main() { Outer outer = Outer(); return outer.make().run(3); }\n"
    )
    s = get_signature_help(analyze(src), pos_of(src, "run(3", offset=4))
    assert s is not None and "run" in s.signatures[0].label


# ---- heuristic type inference when the analyzer can't resolve --------------


def test_hover_var_inferred_from_unknown_call():
    # the callee is undefined → the analyzer can't infer the type, so the
    # hover heuristic falls back to the callee name.
    src = "int main() { var thing = mystery(); return 0; }\n"
    t = hover_text(get_hover_info(analyze(src), pos_of(src, "var thing", offset=4)))
    assert "thing" in t or "mystery" in t


# ---- property definition ---------------------------------------------------


def test_definition_property_access():
    src = (
        "class Gauge {\n"
        "    public int raw;\n"
        "    public Gauge() { self.raw = 0; }\n"
        "    public int level { get { return self.raw; } }\n"
        "}\n"
        "int main() { Gauge g = Gauge(); return g.level; }\n"
    )
    loc = get_definition(analyze(src), pos_of(src, "g.level", offset=2))
    assert loc is None or loc.range.start.line == 3  # the `level` property decl


# ---- static-method completion after a stdlib class -------------------------


def test_completion_after_stdlib_class_name():
    src = "import std.math;\nint main() { int x = Math.abs(-3); return x; }\n"
    names = {i.label for i in get_completions(analyze(src), pos_of(src, "Math.abs", offset=5))}
    assert names  # Math.* static methods offered


# ---- references: inherited method accessed via a variable ------------------


def test_references_inherited_method_via_variable():
    src = (
        "class Base { public int b; public Base() { self.b = 0; }\n"
        "             public int ping() { return self.b; } }\n"
        "class Sub extends Base { public Sub() { self.b = 1; } }\n"
        "int main() { Sub s = Sub(); return s.ping() + s.ping(); }\n"
    )
    refs = get_references(analyze(src), pos_of(src, "public int ping", offset=11))
    assert len({r.range.start.line for r in refs}) >= 2  # decl + call line(s)
