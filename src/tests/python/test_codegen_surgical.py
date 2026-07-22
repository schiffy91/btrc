"""Surgical coverage: list-literal array initializers (`[...]`), GPU dispatch
over a runtime-sized Vector (->len/->data), operator overloading on generic
class instances, and the exported AnalyzerError exception."""

from src.compiler.python.analyzer.core_models import AnalyzerError
from src.tests.python.test_codegen import emit_c


def test_array_list_literal_initializer():
    # `[...]` on an array type → C aggregate initializer.
    c = emit_c("int main() { float[] w = [1.0, 2.0, 3.0]; return 0; }")
    assert "{" in c and "1.0" in c


def test_gpu_dispatch_over_runtime_sized_vector():
    # Dispatching with a Vector<T> argument uses ->len / ->data at the call site.
    c = emit_c(
        "@gpu\nvoid scale(float[] xs, float k) { int i = gpu_id(); xs[i] = xs[i] * k; }\n"
        "int main() { Vector<float> v = new Vector<float>(); v.add(1.0); scale(v, 2.0); return 0; }"
    )
    assert "->len" in c or "->data" in c


def test_operator_overload_on_generic_instances():
    c = emit_c(
        "class Vec2<T> { public T x; public T y; public Vec2(T a, T b) { self.x = a; self.y = b; } }\n"
        "int main() { Vec2<int> a = new Vec2<int>(1, 2); Vec2<int> b = new Vec2<int>(3, 4);\n"
        "             bool eq = a == b; return eq ? 1 : 0; }"
    )
    assert "Vec2_int" in c


def test_analyzer_error_construction():
    err = AnalyzerError("bad thing", 3, 5)
    assert err.line == 3 and err.col == 5
    assert "bad thing at 3:5" in str(err)
