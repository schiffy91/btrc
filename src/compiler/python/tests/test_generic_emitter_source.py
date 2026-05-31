"""Generic-method bodies (monomorphized via the parallel generic emitter) that
use collection literals, sizeof, and method calls through fields/self — driving
the user_emitter expression/statement paths."""

from src.compiler.python.tests.test_codegen import emit_c


def test_generic_method_with_collection_literals_and_sizeof():
    c = emit_c("class Util<T> {\n"
               "    public T v;\n"
               "    public Util(T x) { self.v = x; }\n"
               "    public int compute() {\n"
               "        List<int> tmp = [1, 2, 3];\n"
               "        Map<string, int> m = {\"a\": 1};\n"
               "        int n = sizeof(n);\n"
               "        return tmp.size() + m.size() + n;\n"
               "    }\n"
               "}\n"
               "int main() { Util<int> u = new Util<int>(5); return u.compute(); }")
    assert "Util_int" in c


def test_generic_method_calls_self_and_field_methods():
    c = emit_c("class Helper { public int v; public Helper() { self.v = 0; } public int run() { return 1; } }\n"
               "class Mgr<T> {\n"
               "    public T tag; public Helper helper;\n"
               "    public Mgr(T t) { self.tag = t; self.helper = new Helper(); }\n"
               "    public int direct() { return self.helper.run() + self.other(); }\n"
               "    public int other() { return 2; }\n"
               "}\n"
               "int main() { Mgr<int> m = new Mgr<int>(1); return m.direct(); }")
    assert "Mgr_int" in c


def test_generic_method_with_nested_control_and_literals():
    c = emit_c("class Acc<T> {\n"
               "    public T seed;\n"
               "    public Acc(T s) { self.seed = s; }\n"
               "    public int fold(int n) {\n"
               "        int total = 0;\n"
               "        Vector<int> data = [10, 20, 30];\n"
               "        for x in data { total = total + x; }\n"
               "        if (total > n) { total = total - n; } else { total = total + n; }\n"
               "        return total;\n"
               "    }\n"
               "}\n"
               "int main() { Acc<int> a = new Acc<int>(0); return a.fold(5); }")
    assert "Acc_int" in c
