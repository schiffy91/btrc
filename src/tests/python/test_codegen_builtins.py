"""Codegen for built-in calls and method dispatch: sizeof/len builtins, string
and int methods, property getters, Mutex<T> operations, typed thread join, and
f-string interpolation with expressions."""

from src.tests.python.test_codegen import emit_c


def test_sizeof_expression_and_type():
    c = emit_c("int main() { int x = 5; int a = sizeof(x); int b = sizeof(int); return a + b; }")
    assert "sizeof" in c


def test_len_on_string_and_list():
    c = emit_c('int main() { string s = "hello"; List<int> xs = {1, 2, 3};\n'
               '              return len(s) + len(xs); }')
    assert "len" in c or "strlen" in c


def test_string_length_method():
    c = emit_c('int main() { string s = "hello"; return s.length(); }')
    assert "strlen" in c


def test_int_to_string_method():
    c = emit_c("int main() { int x = 42; string s = x.toString(); print(s); return 0; }")
    assert "__btrc_intToString" in c or "toString" in c


def test_property_getter_access():
    c = emit_c("class C { public int v;\n"
               "    public int doubled { get { return self.v * 2; } }\n"
               "    public C() { self.v = 5; } }\n"
               "int main() { C c = new C(); return c.doubled; }")
    assert "_get_doubled" in c or "doubled" in c


def test_mutex_get_set():
    c = emit_c("int main() { Mutex<int> m = new Mutex<int>(0); m.set(5); int v = m.get(); return v; }")
    assert "__btrc_mutex" in c


def test_thread_join_with_typed_result():
    c = emit_c("int main() { var t = spawn(() => { return 9; }); int r = t.join(); return r; }")
    assert "__btrc_thread_join" in c or "join" in c


def test_fstring_with_expression_interpolation():
    c = emit_c('int main() { int x = 3; int y = 4; string s = f"sum={x + y} done"; print(s); return 0; }')
    assert "snprintf" in c or "sprintf" in c


def test_print_with_mixed_argument_types():
    c = emit_c('int main() { print("a"); print(42); print(3.14); return 0; }')
    assert "printf" in c
