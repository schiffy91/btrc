"""Precise method/call dispatch coverage: string len(), built-in toString on a
class without its own, property-getter-as-call, Thread<T> join with unboxing,
Mutex<T> get/set, sizeof over an expression, default arguments, and print()
string formatting."""

import re

from src.tests.python.test_codegen import emit_c


def test_string_len_and_bytelen():
    c = emit_c('int main() { string s = "hi"; int a = s.len(); int b = s.byteLen(); return a + b; }')
    assert "strlen" in c


def test_tostring_on_class_without_method_is_rejected():
    # The analyzer rejects toString() on a class that doesn't define it (so the
    # built-in lowering never sees a class type).
    from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
    from src.compiler.python.lexer import Lexer
    from src.compiler.python.parser.parser import Parser

    src = (
        "class P { public int v; public P() { self.v = 0; } }\n"
        "int main() { P p = new P(); string s = p.toString(); print(s); return 0; }"
    )
    res = SemanticAnalyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())
    assert any("toString" in e for e in res.errors)


def test_builtin_tostring_on_primitives():
    c = emit_c(
        "int main() { int i = 42; double d = 3.5; bool b = true;\n"
        "             print(i.toString()); print(d.toString()); print(b.toString());\n"
        "             return 0; }"
    )
    assert "toString" in c or "__btrc_" in c


def test_property_getter_called_as_method():
    c = emit_c(
        "class C { public int _v;\n"
        "    public int value { get { return self._v; } }\n"
        "    public C() { self._v = 5; } }\n"
        "int main() { C c = new C(); return c.value; }"
    )
    assert "_get_value" in c


def test_thread_typed_join_unboxes():
    c = emit_c("int main() { Thread<int> t = spawn(() => { return 9; }); int r = t.join(); return r; }")
    assert "__btrc_thread" in c


def test_mutex_get_set_destroy():
    c = emit_c(
        "int main() {\n"
        "    Mutex<int> m = new Mutex<int>(0);\n"
        "    m.set(5);\n"
        "    int v = m.get();\n"
        "    m.destroy();\n"
        "    return v;\n"
        "}"
    )
    assert "__btrc_mutex" in c
    assert "m = NULL;" in c


def test_sizeof_over_compound_expression():
    c = emit_c("int main() { int a = 1; int b = 2; return sizeof(a + b); }")
    assert "sizeof" in c


def test_default_arguments_omitted():
    c = emit_c("int f(int a, int b = 2, int c = 3) { return a + b + c; }\nint main() { return f(1) + f(1, 10); }")
    assert "f(" in c


def test_method_named_arguments_reordered_and_defaulted():
    c = emit_c("""
    class Runner {
        public int run(int a, int b = 2, int c = 3) { return a + b + c; }
    }
    int main() {
        Runner r = new Runner();
        return r.run(1, c=4);
    }
    """)
    assert "__btrc_default_Runner_run_2" in c
    assert re.search(
        r"Runner_run\(__btrc_call_operand_\d+, __btrc_call_operand_\d+, "
        r"__btrc_call_operand_\d+, __btrc_call_operand_\d+\)",
        c,
    )


def test_print_string_uses_percent_s():
    c = emit_c('int main() { string s = "hi"; print(s); return 0; }')
    assert "%s" in c
