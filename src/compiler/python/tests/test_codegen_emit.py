"""Emitter and expression codegen: global variables, virtual dispatch through a
base pointer (vtables), qualified enum-value references, char/tuple values,
null returns, and GPU-result assignment to an existing variable."""

from src.compiler.python.tests.test_codegen import emit_c


def test_global_variable_emitted():
    c = emit_c("int counter = 0;\nint bump() { counter = counter + 1; return counter; }\n"
               "int main() { bump(); return counter; }")
    assert "counter" in c


def test_virtual_dispatch_through_base_pointer():
    c = emit_c("class A { public int v; public A() { self.v = 0; } public int f() { return 1; } }\n"
               "class B extends A { public B() { self.v = 0; } public int f() { return 2; } }\n"
               "int main() { A a = new B(); return a.f(); }")
    assert "A" in c and "B" in c


def test_qualified_enum_value_reference():
    c = emit_c("enum Color { RED, GREEN, BLUE };\n"
               "int main() { Color c = Color.GREEN; if (c == Color.RED) { return 1; } return 0; }")
    assert "Color" in c


def test_char_literal_value_and_print():
    c = emit_c("int main() { char ch = 'X'; print(ch); return 0; }")
    assert "'X'" in c or "88" in c


def test_tuple_literal_value():
    c = emit_c("(int, int) pair() { return (1, 2); }\n"
               "int main() { (int, int) p = pair(); return 0; }")
    assert "Tuple" in c


def test_null_return_from_nullable_function():
    c = emit_c("class N { public int v; public N() { self.v = 0; } }\n"
               "N? find(int x) { if (x > 0) { return new N(); } return null; }\n"
               "int main() { N? n = find(0); if (n == null) { return 0; } return 1; }")
    assert "NULL" in c


def test_gpu_result_assigned_to_existing_variable():
    # `ys = dbl(xs)` (assignment, not declaration) routes the dispatch result
    # through the assign-target readback path.
    c = emit_c("@gpu\nint[] dbl(int[] a) { int i = gpu_id(); return a[i] * 2; }\n"
               "int main() { int[] xs = {1, 2, 3}; int[] ys = {0, 0, 0}; ys = dbl(xs); return 0; }")
    assert "btrc_gpu" in c


def test_string_concatenation_and_comparison():
    c = emit_c('int main() {\n'
               '    string a = "foo"; string b = "bar";\n'
               '    string c = a + b;\n'
               '    bool eq = a.equals(b);\n'
               '    return eq ? 1 : 0;\n'
               '}')
    assert "strcmp" in c or "strcat" in c or "__btrc_str" in c
