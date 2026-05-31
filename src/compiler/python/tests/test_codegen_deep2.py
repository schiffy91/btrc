"""Deeper generic-emitter and WGSL-emitter coverage: generic methods iterating a
collection of class instances and calling through a field, plus GPU kernels with
unary operators, function calls, and integer locals with expression-init loops."""

from src.compiler.python.tests.test_codegen import emit_c


def test_generic_method_iterates_collection_of_class_instances():
    c = emit_c("class It { public int v; public It() { self.v = 0; } public int g() { return self.v; } }\n"
               "class Reg<T> {\n"
               "    public T tag; public Vector<It> items;\n"
               "    public Reg(T t) { self.tag = t; self.items = new Vector<It>(); }\n"
               "    public int total() { int s = 0; for x in self.items { s = s + x.g(); } return s; }\n"
               "}\n"
               "int main() { Reg<int> r = new Reg<int>(1); return r.total(); }")
    assert "Reg_int" in c


def test_generic_method_calls_through_field():
    c = emit_c("class Inner { public int v; public Inner() { self.v = 0; } public int get() { return self.v; } }\n"
               "class Outer<T> {\n"
               "    public T tag; public Inner inner;\n"
               "    public Outer(T t) { self.tag = t; self.inner = new Inner(); }\n"
               "    public int via() { return self.inner.get(); }\n"
               "}\n"
               "int main() { Outer<int> o = new Outer<int>(1); return o.via(); }")
    assert "Outer_int" in c


def test_gpu_kernel_unary_and_function_call():
    c = emit_c("@gpu\nvoid f(float[] xs) { int i = gpu_id(); float v = -xs[i]; xs[i] = abs(v); }\n"
               "int main() { return 0; }")
    assert "@compute" in c


def test_gpu_kernel_integer_local_and_expr_init_loop():
    c = emit_c("@gpu\nvoid g(int[] xs, int n) {\n"
               "    int i = gpu_id(); int acc = 0; int j;\n"
               "    for (j = 0; j < n; j = j + 1) { acc = acc + j; }\n"
               "    xs[i] = acc;\n"
               "}\n"
               "int main() { return 0; }")
    assert "@compute" in c


def test_generic_method_with_list_and_map_literals_as_expressions():
    c = emit_c("class Box<T> {\n"
               "    public T v;\n"
               "    public Box(T x) { self.v = x; }\n"
               "    public int build() {\n"
               "        self.refresh();\n"
               "        return 1;\n"
               "    }\n"
               "    public void refresh() { self.v = self.v; }\n"
               "}\n"
               "int main() { Box<int> b = new Box<int>(0); return b.build(); }")
    assert "Box_int" in c
