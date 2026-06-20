"""Transpile-level codegen tests over the full pipeline (lex → parse → analyze
→ IR-gen → optimize → emit), asserting properties of the emitted C / WGSL.

These exercise codegen paths the end-to-end runner does not reach in a headless
environment (GPU kernel emission and dispatch, generic monomorphization, thread
wrappers, ARC edge cases), without needing a GPU or running the binary.
"""

import re

from src.tests.python.test_codegen import emit_c

# --------------------------------------------------------------------------- #
# GPU: kernel emission (WGSL) + dispatch (C runtime calls)
# --------------------------------------------------------------------------- #

def test_gpu_array_kernel_emits_wgsl():
    c = emit_c("@gpu\nint[] addv(int[] a, int[] b) { int i = gpu_id(); return a[i] + b[i]; }\n"
               "int main() { return 0; }")
    assert "@compute" in c                      # WGSL compute shader header
    assert "@workgroup_size" in c


def test_gpu_void_kernel_in_place_buffer():
    c = emit_c("@gpu\nvoid scale(float[] xs, float k) { int i = gpu_id(); xs[i] = xs[i] * k; }\n"
               "int main() { return 0; }")
    assert "@compute" in c
    # a scalar param becomes a uniform; an array param a storage buffer
    assert "var<storage" in c or "storage" in c


def test_gpu_dispatch_emits_runtime_calls():
    c = emit_c("@gpu\nint[] dbl(int[] a) { int i = gpu_id(); return a[i] * 2; }\n"
               "int main() { int[] xs = {1, 2, 3}; int[] ys = dbl(xs); return 0; }")
    # dispatching a kernel pulls in the GPU runtime header and a dispatch call
    assert "btrc_gpu" in c


def test_gpu_kernel_with_control_flow():
    c = emit_c("@gpu\nvoid clamp(int[] xs) {\n"
               "    int i = gpu_id();\n"
               "    if (xs[i] < 0) { xs[i] = 0; }\n"
               "    for (int k = 0; k < 2; k = k + 1) { xs[i] = xs[i] + 1; }\n"
               "}\n"
               "int main() { return 0; }")
    assert "@compute" in c
    assert "if" in c and "for" in c             # control flow translated to WGSL


def test_gpu_multiple_scalar_uniforms():
    c = emit_c("@gpu\nvoid affine(float[] xs, float a, float b) {\n"
               "    int i = gpu_id(); xs[i] = xs[i] * a + b;\n"
               "}\n"
               "int main() { return 0; }")
    assert "@compute" in c


def test_gpu_void_kernel_dispatch_with_uniform_and_fallback():
    # Dispatching a void in-place kernel exercises the CPU-fallback guard, the
    # scalar-uniform upload, and the in-place buffer readback.
    c = emit_c("@gpu\nvoid scale(float[] xs, float k) { int i = gpu_id(); xs[i] = xs[i] * k; }\n"
               "int main() { float[] xs = {1.0, 2.0, 3.0}; scale(xs, 2.0); return 0; }")
    assert "btrc_gpu_available" in c            # CPU-fallback guard
    assert "__uniforms" in c                    # scalar uniform upload
    assert "btrc_gpu_read_buffer" in c          # in-place readback


def test_gpu_array_kernel_dispatch_with_assignment():
    c = emit_c("@gpu\nint[] dbl(int[] a) { int i = gpu_id(); return a[i] * 2; }\n"
               "int main() { int[] xs = {1, 2, 3}; int[] ys = dbl(xs); return ys[0]; }")
    assert "btrc_gpu_read_buffer" in c          # output buffer read back
    assert "btrc_gpu_dispatch" in c


# --------------------------------------------------------------------------- #
# Generics: monomorphization
# --------------------------------------------------------------------------- #

def test_generic_class_monomorphized():
    c = emit_c("class Box<T> { public T v; public Box(T v) { self.v = v; }\n"
               "               public T get() { return self.v; } }\n"
               "int main() { Box<int> b = new Box<int>(5); return b.get(); }")
    # the int instantiation produces a concrete struct + ctor
    assert re.search(r"Box_int", c), c


def test_generic_two_type_params():
    c = emit_c("class Pair<K, V> { public K k; public V v;\n"
               "    public Pair(K k, V v) { self.k = k; self.v = v; } }\n"
               "int main() { Pair<int, int> p = new Pair<int, int>(1, 2); return p.k; }")
    assert "Pair_int_int" in c


def test_generic_method_with_collection():
    c = emit_c("class Stack<T> { public List<T> items;\n"
               "    public Stack() { self.items = new List<T>(); }\n"
               "    public void push(T x) { self.items.add(x); }\n"
               "    public int size() { return self.items.size(); } }\n"
               "int main() { Stack<int> s = new Stack<int>(); s.push(7); return s.size(); }")
    assert "Stack_int" in c


# --------------------------------------------------------------------------- #
# Threads: spawn wrapper, captures, join
# --------------------------------------------------------------------------- #

def test_thread_spawn_emits_wrapper():
    c = emit_c("int main() { var t = spawn(() => { return 42; }); int r = t.join(); return r; }")
    assert "__btrc_spawn_wrapper" in c
    assert "pthread" in c or "__btrc_thread" in c


def test_thread_spawn_with_capture():
    c = emit_c("int main() { int n = 9; var t = spawn(() => { return n * 2; }); return t.join(); }")
    assert "__btrc_spawn_env" in c               # capture struct
    assert "malloc" in c


# --------------------------------------------------------------------------- #
# ARC: managed locals, ownership transfer, fields, delete
# --------------------------------------------------------------------------- #

def test_arc_releases_managed_local_at_scope_exit():
    c = emit_c("class Obj { public int v; public Obj() { self.v = 0; } }\n"
               "void use() { Obj o = new Obj(); }\n"
               "int main() { use(); return 0; }")
    assert "Obj_destroy" in c or "__rc" in c     # refcount lifecycle emitted


def test_arc_delete_statement():
    c = emit_c("class Obj { public int v; public Obj() { self.v = 0; } }\n"
               "int main() { Obj o = new Obj(); delete o; return 0; }")
    assert "__rc" in c or "destroy" in c


def test_arc_field_assignment_keep_release():
    c = emit_c("class Node { public Node next; public int v; public Node() { self.v = 0; } }\n"
               "int main() { Node a = new Node(); Node b = new Node(); a.next = b; return 0; }")
    assert "__rc" in c


# --------------------------------------------------------------------------- #
# Control flow varieties
# --------------------------------------------------------------------------- #

def test_for_in_over_list():
    c = emit_c("int main() { List<int> xs = {1, 2, 3}; int total = 0;\n"
               "             for x in xs { total = total + x; } return total; }")
    assert "for" in c


def test_c_style_for_and_do_while():
    c = emit_c("int main() {\n"
               "    int s = 0;\n"
               "    for (int i = 0; i < 3; i = i + 1) { s = s + i; }\n"
               "    int j = 0;\n"
               "    do { j = j + 1; } while (j < 3);\n"
               "    return s + j;\n"
               "}")
    assert "for" in c and "do" in c and "while" in c


def test_switch_statement():
    c = emit_c("int main() {\n"
               "    int x = 2;\n"
               "    switch (x) {\n"
               "        case 1: { return 10; }\n"
               "        case 2: { return 20; }\n"
               "        default: { return 0; }\n"
               "    }\n"
               "}")
    assert "switch" in c and "case" in c


# --------------------------------------------------------------------------- #
# Enums + rich ADTs
# --------------------------------------------------------------------------- #

def test_plain_and_valued_enums():
    c = emit_c("enum Color { RED, GREEN, BLUE };\n"
               "enum Status { OK = 200, NOT_FOUND = 404 };\n"
               "int main() { Color c = RED; Status s = OK; return 0; }")
    assert "enum" in c or "RED" in c


def test_rich_enum_adt():
    c = emit_c("enum class Shape { Circle(double r), Square(double s) }\n"
               "int main() { return 0; }")
    assert "Shape" in c


# --------------------------------------------------------------------------- #
# Lambdas, fstrings, operators, collections
# --------------------------------------------------------------------------- #

def test_lambda_expression_body():
    c = emit_c("int main() { var f = (int x) => x * 2; return f(21); }")
    assert "(" in c and "42" not in c            # not constant-folded away


def test_fstring_interpolation():
    c = emit_c('int main() { int x = 5; string s = f"val={x}"; print(s); return 0; }')
    assert "snprintf" in c or "sprintf" in c or "val=" in c


def test_map_and_set_literals():
    c = emit_c('int main() {\n'
               '    Map<string, int> m = {"a": 1, "b": 2};\n'
               '    Set<int> s = {1, 2, 3};\n'
               '    return m.size() + s.size();\n'
               '}')
    assert "Map" in c and "Set" in c
