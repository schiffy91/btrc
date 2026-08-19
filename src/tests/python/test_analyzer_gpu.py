"""SemanticAnalyzer validation of @gpu kernels: the constrained subset of types a GPU
kernel may use. Each test asserts the specific diagnostic, not just that some
error occurred."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def errors(src):
    return SemanticAnalyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse()).errors


def _has(msgs, sub):
    return any(sub.lower() in m.lower() for m in msgs)


def test_gpu_scalar_return_rejected():
    # A @gpu kernel must return void or an array, not a bare scalar.
    errs = errors("@gpu\nint f(int[] a) { int i = gpu_id(); return a[i]; }\nint main() { return 0; }")
    assert errs


def test_gpu_pointer_param_rejected():
    # Class types are pointers; GPU kernels can't take them.
    errs = errors(
        "class Obj { public int v; public Obj() { self.v = 0; } }\n"
        "@gpu\nvoid f(Obj o) { int i = gpu_id(); }\nint main() { return 0; }"
    )
    assert errs


def test_gpu_nullable_param_rejected():
    errs = errors("@gpu\nvoid f(int? x) { int i = gpu_id(); }\nint main() { return 0; }")
    assert errs


def test_gpu_generic_param_rejected():
    errs = errors("@gpu\nvoid f(List<int> xs) { int i = gpu_id(); }\nint main() { return 0; }")
    assert errs


def test_gpu_non_scalar_param_type_rejected():
    # string is not a GPU scalar element type.
    errs = errors("@gpu\nvoid f(string s) { int i = gpu_id(); }\nint main() { return 0; }")
    assert errs


def test_gpu_disallowed_array_elem_rejected():
    errs = errors("@gpu\nvoid f(string[] s) { int i = gpu_id(); }\nint main() { return 0; }")
    assert errs


def test_gpu_valid_kernel_has_no_errors():
    errs = errors(
        "@gpu\nint[] addv(int[] a, int[] b) { int i = gpu_id(); return a[i] + b[i]; }\nint main() { return 0; }"
    )
    assert errs == []


def test_gpu_user_function_call_without_wgsl_definition_is_rejected():
    errs = errors(
        "float helper(float x) { return x * 2.0; }\n"
        "@gpu\nvoid f(float[] values) { int i = gpu_id(); "
        "values[i] = helper(values[i]); }\n"
        "int main() { return 0; }"
    )

    assert _has(errs, "call to 'helper' has no WGSL definition")
