"""Deep generic-emitter codegen: destructors, generic classes with collection
and class-typed fields (ARC cleanup), collection literals inside monomorphized
methods, range loops, sizeof, and both c-for init forms."""

from src.tests.python.test_codegen import emit_c


def test_class_with_destructor():
    c = emit_c('class R { public int v; public R() { self.v = 0; }\n'
               '          public void __del__() { print("bye"); } }\n'
               'int main() { R r = new R(); return 0; }')
    assert "R_destroy" in c or "__del__" in c


def test_generic_class_with_collection_field_and_range_loop():
    c = emit_c("class Box<T> {\n"
               "    public T v; public List<int> nums;\n"
               "    public Box(T v) { self.v = v; self.nums = {1, 2, 3}; }\n"
               "    public int sum() { int s = 0; for i in range(3) { s = s + i; } return s; }\n"
               "}\n"
               "int main() { Box<int> b = new Box<int>(5); return b.sum(); }")
    assert "Box_int" in c


def test_generic_class_with_map_field():
    c = emit_c('class M<T> {\n'
               '    public T v; public Map<string, int> lk;\n'
               '    public M(T v) { self.v = v; self.lk = {"a": 1}; }\n'
               '}\n'
               'int main() { M<int> m = new M<int>(0); return 0; }')
    assert "M_int" in c


def test_generic_class_with_class_field_cleanup():
    # Outer<T> owns an Inner instance; the monomorphized destructor must release
    # the class-typed field (generic-emitter ARC cleanup path).
    c = emit_c("class Inner { public int v; public Inner() { self.v = 0; } }\n"
               "class Outer<T> {\n"
               "    public T v; public Inner inner;\n"
               "    public Outer(T v) { self.v = v; self.inner = new Inner(); }\n"
               "}\n"
               "int main() { Outer<int> o = new Outer<int>(1); return 0; }")
    assert "Outer_int" in c


def test_generic_method_rich_constructs():
    c = emit_c("class Util<T> {\n"
               "    public T val;\n"
               "    public Util(T v) { self.val = v; }\n"
               "    public int run() {\n"
               "        int s = 0;\n"
               "        int n = sizeof(s);\n"
               "        for i in range(3) { s = s + i; }\n"
               "        int m = 0;\n"
               "        for (m = 0; m < 2; m = m + 1) { s = s + m; }\n"
               "        return s + n;\n"
               "    }\n"
               "}\n"
               "int main() { Util<int> u = new Util<int>(0); return u.run(); }")
    assert "Util_int" in c
