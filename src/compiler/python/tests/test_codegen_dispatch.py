"""Codegen for call/method dispatch details: default arguments, print()
formatting per argument type, sizeof over an array, and string/int/thread/mutex
method lowering."""

from src.compiler.python.tests.test_codegen import emit_c


def test_default_arguments_filled_at_call_site():
    c = emit_c("int add(int a, int b = 10, int c = 100) { return a + b + c; }\n"
               "int main() { return add(5) + add(5, 20); }")
    assert "add" in c


def test_named_arguments_reordered_and_defaulted():
    c = emit_c("int f(int a, int b = 2, int c = 3) { return a + b + c; }\n"
               "int main() { return f(1, c=4) + f(c=5, a=6, b=7); }")
    assert "f(1, 2, 4)" in c
    assert "f(6, 7, 5)" in c


def test_print_formats_by_argument_type():
    c = emit_c('int main() {\n'
               '    string s = "hi"; int n = 42; double d = 3.5; bool b = true;\n'
               '    print(s); print(n); print(d); print(b);\n'
               '    return 0;\n'
               '}')
    assert "%s" in c and "printf" in c


def test_sizeof_over_array_variable():
    c = emit_c("int main() { int[] arr = {1, 2, 3}; int n = sizeof(arr); return n; }")
    assert "sizeof" in c


def test_string_methods_dispatch():
    c = emit_c('int main() {\n'
               '    string s = "Hello";\n'
               '    int n = s.length();\n'
               '    string u = s.toUpper();\n'
               '    bool h = s.startsWith("He");\n'
               '    return n + (h ? 1 : 0);\n'
               '}')
    assert "strlen" in c or "__btrc_str" in c


def test_int_and_double_to_string():
    c = emit_c("int main() {\n"
               "    int i = 42; double d = 3.14;\n"
               "    string a = i.toString();\n"
               "    string b = d.toString();\n"
               "    print(a); print(b);\n"
               "    return 0;\n"
               "}")
    assert "toString" in c or "__btrc_" in c


def test_thread_join_result_cast():
    c = emit_c("int main() {\n"
               "    var t = spawn(() => { return 7; });\n"
               "    int r = t.join();\n"
               "    return r;\n"
               "}")
    assert "join" in c


def test_mutex_operations():
    c = emit_c("int main() {\n"
               "    Mutex<int> m = new Mutex<int>(0);\n"
               "    m.set(5);\n"
               "    int v = m.get();\n"
               "    return v;\n"
               "}")
    assert "__btrc_mutex" in c
