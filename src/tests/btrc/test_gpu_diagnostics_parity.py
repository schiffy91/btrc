"""Both compilers accept and reject the same ``@gpu`` programs identically.

Each probe is compiled by the Python reference compiler and by the
self-hosted ``btrcc``. An invalid probe must fail in both with the same first
diagnostic -- identical message, line and column -- and that diagnostic is
pinned below, so rewording it in one compiler alone fails here. A valid probe
must compile in both, and every WGSL module either compiler emits must be
byte-identical to the other's and, where ``naga`` is installed, validate.
The ``gpu/`` corpus and the GPU fixtures get the same WGSL check with dead-code
elimination off, so every kernel they declare is emitted.

Kernel validation belongs to the analyzer stage in both compilers, as Python's
GpuAnalyzer always did, so most invalid probes declare a kernel that nothing
dispatches or calls: an unreachable invalid kernel is still an invalid program.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import REFERENCE_DIAGNOSTIC, SELFHOST_DIAGNOSTIC, GpuDiagnostic

REPO = Path(__file__).resolve().parents[3]
NAGA = shutil.which("naga")
SHADER = re.compile(r'static (?:const )?char\* (\w+)_wgsl = ("(?:\\.|[^"])*");')
UNREACHABLE_MAIN = "int main() { return 0; }"
CORPUS = (
    *sorted((REPO / "src/tests/gpu").glob("*.btrc")),
    REPO / "src/tests/btrc/fixtures/GpuCheckedSemantics.btrc",
    REPO / "src/tests/btrc/fixtures/GpuCompoundSemantics.btrc",
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")


@dataclass(frozen=True)
class GpuProbe:
    """One source program and its pinned outcome."""

    name: str
    source: str
    diagnostic: GpuDiagnostic | None = None
    kernels: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpuOutcome:
    """What one compiler observably did with one program."""

    returncode: int
    diagnostic: GpuDiagnostic | None
    shaders: tuple[tuple[str, str], ...]


INVALID_PROBES = (
    GpuProbe(
        "param-nullable",
        "@gpu void k(int? x) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': nullable types not allowed in parameter 'x'", 1, 6),
    ),
    GpuProbe(
        "param-pointer",
        "@gpu void k(int* p) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': pointer types not allowed in parameter 'p'", 1, 6),
    ),
    GpuProbe(
        "param-const-array",
        "@gpu void k(const int[] xs) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic(
            "@gpu function 'k': GPU array buffers are read-write and cannot be const- or volatile-qualified in parameter 'xs'",
            1,
            6,
        ),
    ),
    GpuProbe(
        "param-volatile-array",
        "@gpu void k(volatile int[] xs) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic(
            "@gpu function 'k': GPU array buffers are read-write and cannot be const- or volatile-qualified in parameter 'xs'",
            1,
            6,
        ),
    ),
    GpuProbe(
        "param-bool-array",
        "@gpu void k(bool[] xs) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': array element type must be int or float in parameter 'xs', got 'bool'", 1, 6),
    ),
    GpuProbe(
        "param-string",
        "@gpu void k(int[] xs, string s) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': type 'string' not allowed in parameter 's' (use int, float, or bool)", 1, 6),
    ),
    GpuProbe(
        "param-generic",
        "class Vector<T> { public T* data; public int len; }\n@gpu void k(Vector<int> v) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': generic types not allowed in parameter 'v'", 2, 6),
    ),
    GpuProbe(
        "param-class",
        "class Point { public int x; }\n@gpu void k(Point p) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': type 'Point' not allowed in parameter 'p' (use int, float, or bool)", 2, 6),
    ),
    GpuProbe(
        "param-double",
        "@gpu void k(double d) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': type 'double' not allowed in parameter 'd' (use int, float, or bool)", 1, 6),
    ),
    GpuProbe(
        "var-float-literal-out-of-f32-range",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nvar y = 1e40;\nfs[i] = y;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': floating literal is outside the WGSL f32 range", 3, 9),
    ),
    GpuProbe(
        "var-double-cast",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nvar s = (double)1;\nfs[i] = 1.0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': cast target 'double' has no WGSL scalar representation", 3, 9),
    ),
    GpuProbe(
        "return-int",
        "@gpu int k(int[] xs) {\nreturn 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': return type must be void, int[], or float[], got 'int'", 1, 6),
    ),
    GpuProbe(
        "return-bool-array",
        "@gpu bool[] k(int[] xs) {\nreturn xs[gpu_id()] > 0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': return type must be void, int[], or float[], got 'bool[]'", 1, 6),
    ),
    GpuProbe(
        "return-double-array",
        "@gpu double[] k(int[] xs) {\nreturn 1.0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': return type must be void, int[], or float[], got 'double[]'", 1, 6),
    ),
    GpuProbe(
        "default-array-no-capacity",
        "@gpu void k(int[] xs = null) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Default for parameter 'xs' has no provable readable GPU buffer capacity", 1, 24),
    ),
    GpuProbe(
        "local-pointer",
        "@gpu void k(int[] xs) {\nint* p = null;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': null has no WGSL value representation", 2, 10),
    ),
    GpuProbe(
        "local-string",
        '@gpu void k(int[] xs) {\nstring s = "a";\n}\nint main() { return 0; }\n',
        GpuDiagnostic("@gpu function 'k': string literal has no WGSL lowering", 2, 12),
    ),
    GpuProbe(
        "local-array",
        "@gpu void k(int[] xs) {\nint ys[2];\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': array types not allowed in variable 'ys'", 2, 1),
    ),
    GpuProbe(
        "local-nullable",
        "@gpu void k(int[] xs) {\nint? y = 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Cannot assign 'int' to variable 'y' of type 'int*'", 2, 1),
    ),
    GpuProbe(
        "local-var-array",
        "@gpu void k(int[] xs) {\nvar a = xs;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': pointer types not allowed in variable 'a'", 2, 1),
    ),
    GpuProbe(
        "local-var-lambda-call",
        "@gpu void k(int[] xs) {\nvar f = (int a) => a;\nxs[0] = f(1);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': lambda has no WGSL lowering", 2, 9),
    ),
    GpuProbe(
        "local-double",
        "@gpu void k(int[] xs) {\ndouble d = 1.0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': type 'double' not allowed in variable 'd' (use int, float, or bool)", 2, 1),
    ),
    GpuProbe(
        "stmt-for-in",
        "@gpu void k(int[] xs) {\nfor x in xs { int y = x; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Array for-in iterable has no provable element capacity", 2, 1),
    ),
    GpuProbe(
        "stmt-try",
        "@gpu void k(int[] xs) {\ntry { int y = 1; } catch (string e) { int z = 2; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': try/catch statement is not allowed in GPU functions", 2, 1),
    ),
    GpuProbe(
        "stmt-throw",
        '@gpu void k(int[] xs) {\nthrow "x";\n}\nint main() { return 0; }\n',
        GpuDiagnostic("@gpu function 'k': throw statement is not allowed in GPU functions", 2, 1),
    ),
    GpuProbe(
        "stmt-switch",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nswitch (i) { case 0: break; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': switch statement is not allowed in GPU functions", 3, 1),
    ),
    GpuProbe(
        "stmt-do-while",
        "@gpu void k(int[] xs) {\nint i = 0;\ndo { i++; } while (i < 3);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': do-while statement is not allowed in GPU functions", 3, 1),
    ),
    GpuProbe(
        "stmt-non-update-expr",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] + 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic(
            "@gpu function 'k': expression statement must be an assignment, increment, decrement, or WGSL built-in call",
            3,
            1,
        ),
    ),
    GpuProbe(
        "stmt-for-bad-update",
        "@gpu void k(int[] xs) {\nfor (int j = 0; j < 3; j + 1) { xs[0] = j; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': for-loop initializer/update must update a variable or buffer element", 2, 24),
    ),
    GpuProbe(
        "stmt-for-bad-comma-update",
        "@gpu void k(int[] xs) {\nfor (int j = 0; j < 3; j++, j + 1) { xs[0] = j; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': for-loop initializer/update must update a variable or buffer element", 2, 29),
    ),
    GpuProbe(
        "stmt-if-int-condition",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nif (i) { xs[i] = 1; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': control-flow condition must be bool, got 'int'", 3, 5),
    ),
    GpuProbe(
        "stmt-while-int-condition",
        "@gpu void k(int[] xs) {\nint i = 3;\nwhile (i) { i--; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': control-flow condition must be bool, got 'int'", 3, 8),
    ),
    GpuProbe(
        "stmt-for-int-condition",
        "@gpu void k(int[] xs) {\nfor (int j = 3; j; j--) { xs[0] = j; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': control-flow condition must be bool, got 'int'", 2, 17),
    ),
    GpuProbe(
        "stmt-void-return-value",
        "@gpu void k(int[] xs) {\nreturn 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Void function or method cannot return a value", 2, 1),
    ),
    GpuProbe(
        "stmt-nested-block",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\n{ xs[i] = 1; }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': nested block statement is not allowed in GPU functions", 3, 1),
    ),
    GpuProbe(
        "update-bitwise-int-bool",
        "@gpu void k(int[] xs) {\nint x = 1;\nx &= true;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': compound assignment operands must have the same GPU scalar type", 3, 1),
    ),
    GpuProbe(
        "update-bitwise-bool-int",
        "@gpu void k(int[] xs) {\nbool b = true;\nb |= 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': compound assignment operands must have the same GPU scalar type", 3, 1),
    ),
    GpuProbe(
        "update-remainder-value-float",
        "@gpu void k(int[] xs) {\nint x = 5;\nx %= 2.0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': remainder assignment operand must be int, got 'float'", 3, 6),
    ),
    GpuProbe(
        "update-assign-gpu-id",
        "@gpu void k(int[] xs) {\ngpu_id() = 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Assignment target is not assignable", 2, 1),
    ),
    GpuProbe(
        "update-increment-call",
        "@gpu void k(int[] xs) {\ngpu_id()++;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Unary operator '++' is not defined for 'int'", 2, 1),
    ),
    GpuProbe(
        "expr-ternary-arrays",
        "@gpu void k(int[] xs, int[] ys) {\nint i = gpu_id();\nxs[i] = (i > 0 ? xs : ys)[0];\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': ternary expressions cannot select whole GPU arrays", 3, 10),
    ),
    GpuProbe(
        "expr-min-bool",
        "@gpu void k(int[] xs) {\nbool b = min(true, false);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': min() requires int or float arguments in GPU functions", 2, 10),
    ),
    GpuProbe(
        "expr-cast-string",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = (int)(string)i;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Pointer/integer casts require intptr_t or uintptr_t", 3, 14),
    ),
    GpuProbe(
        "expr-char-literal",
        "@gpu void k(int[] xs) {\nxs[0] = 'a';\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': character literal has no WGSL lowering", 2, 9),
    ),
    GpuProbe(
        "expr-self-in-kernel",
        "@gpu void k(int[] xs) {\nxs[0] = xs.length;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': field and method access has no WGSL lowering", 2, 9),
    ),
    GpuProbe(
        "expr-source-shadows-builtin",
        "float sqrt(float x) { return x; }\n@gpu void k(float[] fs) {\nfs[0] = sqrt(2.0);\n}\nint main() { return 0; }\n",
        GpuDiagnostic(
            "@gpu function 'k': call to 'sqrt' has no WGSL definition because it resolves to a source symbol", 3, 9
        ),
    ),
    GpuProbe(
        "expr-int-literal-range",
        "@gpu void k(int[] xs) {\nxs[0] = 3000000000;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': integer literal is outside the WGSL i32 range", 2, 9),
    ),
    GpuProbe(
        "expr-long-suffix",
        "@gpu void k(int[] xs) {\nxs[0] = 1L;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': integer literal must be int, got 'long'", 2, 9),
    ),
    GpuProbe(
        "expr-unsigned-suffix",
        "@gpu void k(int[] xs) {\nxs[0] = 1u;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': integer literal must be int, got 'unsigned int'", 2, 9),
    ),
    GpuProbe(
        "expr-float-literal-range",
        "@gpu void k(float[] fs) {\nfs[0] = 1e39;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': floating literal is outside the WGSL f32 range", 2, 9),
    ),
    GpuProbe(
        "expr-null",
        "@gpu void k(int[] xs) {\nbool b = null == null;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': null has no WGSL value representation", 2, 10),
    ),
    GpuProbe(
        "expr-global",
        "int g = 3;\n@gpu void k(int[] xs) {\nxs[0] = g;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': identifier 'g' is not a GPU parameter or local", 3, 9),
    ),
    GpuProbe(
        "expr-remainder-float",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfs[i] = fs[i] % 2.0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': remainder operand must be int, got 'float'", 3, 9),
    ),
    GpuProbe(
        "expr-bitwise-mixed",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nbool b = true;\nxs[i] = i & b;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': bitwise operands must have the same int or bool GPU type", 4, 9),
    ),
    GpuProbe(
        "expr-bitnot-float",
        "@gpu void k(float[] fs) {\nfloat f = ~fs[0];\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Unary operator '~' is not defined for 'float'", 2, 11),
    ),
    GpuProbe(
        "expr-not-int",
        "@gpu void k(int[] xs) {\nbool b = !xs[0];\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': logical-not operand must be bool, got 'int'", 2, 11),
    ),
    GpuProbe(
        "expr-negate-bool",
        "@gpu void k(int[] xs) {\nbool b = -true;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Unary operator '-' is not defined for 'bool'", 2, 10),
    ),
    GpuProbe(
        "expr-increment-in-expression",
        "@gpu void k(int[] xs) {\nint x = 1;\nint y = x++;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': '++' is only supported as a standalone update statement", 3, 9),
    ),
    GpuProbe(
        "expr-method-call",
        "@gpu void k(int[] xs) {\nint n = xs.len();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': indirect and method calls have no WGSL definition", 2, 9),
    ),
    GpuProbe(
        "expr-source-call",
        "int helper() { return 1; }\n@gpu void k(int[] xs) {\nxs[0] = helper();\n}\nint main() { return 0; }\n",
        GpuDiagnostic(
            "@gpu function 'k': call to 'helper' has no WGSL definition because it resolves to a source symbol", 3, 9
        ),
    ),
    GpuProbe(
        "expr-unknown-call",
        "@gpu void k(int[] xs) {\nxs[0] = mystery();\n}\nint main() { return 0; }\n",
        GpuDiagnostic(
            "@gpu function 'k': call to 'mystery' has no WGSL definition; only gpu_id() and WGSL built-ins are allowed",
            2,
            9,
        ),
    ),
    GpuProbe(
        "expr-gpu-id-arguments",
        "@gpu void k(int[] xs) {\nint i = gpu_id(1);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("gpu_id() takes no arguments", 2, 9),
    ),
    GpuProbe(
        "expr-sqrt-int",
        "@gpu void k(float[] fs) {\nfs[0] = sqrt(1);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': sqrt() requires float arguments in GPU functions", 2, 9),
    ),
    GpuProbe(
        "expr-max-mixed",
        "@gpu void k(float[] fs) {\nfs[0] = max(1, 2.0);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': max() arguments must have the same GPU scalar type", 2, 9),
    ),
    GpuProbe(
        "expr-clamp-arity",
        "@gpu void k(float[] fs) {\nfs[0] = clamp(1.0, 2.0);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': clamp() expects 3 argument(s), got 2", 2, 9),
    ),
    GpuProbe(
        "expr-abs-bool",
        "@gpu void k(int[] xs) {\nbool b = abs(true);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': abs() requires int or float arguments in GPU functions", 2, 10),
    ),
    GpuProbe(
        "expr-float-index",
        "@gpu void k(int[] xs) {\nxs[1.5] = 1;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Index expression must have an integral type", 2, 4),
    ),
    GpuProbe(
        "expr-assignment-value",
        "@gpu void k(int[] xs) {\nint x = 1;\nint y = (x = 2);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': assignment is only supported as a standalone update statement", 3, 10),
    ),
    GpuProbe(
        "expr-ternary-int-condition",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = i ? 1 : 2;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': ternary condition must be bool, got 'int'", 3, 9),
    ),
    GpuProbe(
        "expr-cast-pointer",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = (int)(long)i;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': cast target 'long' has no WGSL scalar representation", 3, 14),
    ),
    GpuProbe(
        "expr-field-access",
        "@gpu void k(int[] xs) {\nint n = xs.length;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': field and method access has no WGSL lowering", 2, 9),
    ),
    GpuProbe(
        "expr-lambda",
        "@gpu void k(int[] xs) {\nvar f = (int a) => a;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': lambda has no WGSL lowering", 2, 9),
    ),
    GpuProbe(
        "expr-string-literal",
        '@gpu void k(int[] xs) {\nbool b = "a" == "b";\n}\nint main() { return 0; }\n',
        GpuDiagnostic("@gpu function 'k': string literal has no WGSL lowering", 2, 10),
    ),
    GpuProbe(
        "expr-sizeof",
        "@gpu void k(int[] xs) {\nxs[0] = sizeof(int);\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': sizeof has no WGSL lowering", 2, 9),
    ),
    GpuProbe(
        "update-remainder-float",
        "@gpu void k(float[] fs) {\nfs[0] %= 2.0;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': remainder assignment target must be int, got 'float'", 2, 1),
    ),
    GpuProbe(
        "update-compound-mismatch",
        "@gpu void k(float[] fs) {\nfloat f = 1.0;\nf += 1;\nfs[0] = f;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': compound assignment operands must have the same GPU scalar type", 3, 1),
    ),
    GpuProbe(
        "update-scalar-param",
        "@gpu void k(int[] xs, int n) {\nn = 3;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': scalar parameter 'n' is a read-only uniform", 2, 1),
    ),
    GpuProbe(
        "update-whole-array",
        "@gpu void k(int[] xs, int[] ys) {\nxs = ys;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': whole GPU arrays cannot be assigned or incremented", 2, 1),
    ),
    GpuProbe(
        "update-whole-array-increment",
        "@gpu void k(int[] xs) {\nxs++;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Unary operator '++' is not defined for 'int[]'", 2, 1),
    ),
    GpuProbe(
        "update-bool-increment",
        "@gpu void k(int[] xs) {\nbool b = true;\nb++;\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Unary operator '++' is not defined for 'bool'", 3, 1),
    ),
    GpuProbe(
        "gpu-id-outside-kernel",
        "int main() { int i = gpu_id(); return i; }\n",
        GpuDiagnostic("gpu_id() can only be called inside @gpu functions", 1, 22),
    ),
    GpuProbe(
        "array-result-context",
        "@gpu int[] k(int[] xs) {\nreturn xs[gpu_id()];\n}\nint main() { int[] xs = {1}; return k(xs)[0]; }\n",
        GpuDiagnostic(
            "Array-returning @gpu call is only valid as an array declaration initializer or direct array assignment statement",
            4,
            37,
        ),
    ),
    GpuProbe(
        "gpu-method",
        "class C {\n    public @gpu void k(int[] xs) { int i = gpu_id(); }\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu is only supported on top-level functions; methods have no WGSL dispatch lowering", 2, 5),
    ),
    GpuProbe(
        "reachable-invalid",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = xs[i] % 2.0;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        GpuDiagnostic("@gpu function 'k': remainder operand must be int, got 'float'", 3, 17),
    ),
    GpuProbe(
        "bodyless-kernel",
        "@gpu void k(int[] xs);\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': GPU kernels require a body", 1, 6),
    ),
    GpuProbe(
        "param-typedef",
        "typedef int myint;\n@gpu void k(myint n, int[] xs) {\nint i = gpu_id();\n}\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu function 'k': type 'myint' not allowed in parameter 'n' (use int, float, or bool)", 2, 6),
    ),
    GpuProbe(
        "unreachable-invalid-beside-valid",
        "@gpu void bad(int[] xs) { xs[0] = 1.5 % 2.0; }\n@gpu void good(int[] xs) { int i = gpu_id(); xs[i] = 1; }\nint main() { int[] xs = {1}; good(xs); return 0; }\n",
        GpuDiagnostic("@gpu function 'bad': remainder operand must be int, got 'float'", 1, 35),
    ),
)
VALID_PROBES = (
    GpuProbe(
        "stmt-bare-builtin-call",
        "@gpu void k(float[] fs) {\nsqrt(2.0);\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-var-local",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nvar y = xs[i] + 1;\nxs[i] = y;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-unused",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = xs[i] * 2;\n}\nint main() { return 0; }\n",
        kernels=(),
    ),
    GpuProbe(
        "valid-int-scale",
        "@gpu void k(int[] xs, int n) {\nint i = gpu_id();\nxs[i] = xs[i] * n;\n}\nint main() { int[] xs = {1, 2}; k(xs, 3); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-uniform-first",
        "@gpu void k(int n, int[] xs) {\nint i = gpu_id();\nxs[i] = xs[i] + n;\n}\nint main() { int[] xs = {1, 2}; k(3, xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-float-math",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfs[i] = sqrt(fs[i]) + floor(fs[i]) * pow(fs[i], 2.0);\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-round-clamp",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfs[i] = clamp(round(fs[i]), 0.0, 10.0);\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-min-max-abs",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = max(min(xs[i], 3), abs(xs[i] - 5));\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-ternary",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = xs[i] > 2 ? xs[i] : i + 1;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-ternary-nested-condition",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfs[i] = fs[i] > 1.0 && i < 2 ? 1 : 2.5;\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-for-loop",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nint total = 0;\nfor (int j = 0; j < 4; j++) { if (j == 2) { continue; } total += j; }\nxs[i] = total;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-for-comma-header",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nint total = 0;\nint j;\nint m;\nfor (j = 0, m = 3; j < 4; j++, m--) { total += j * m; }\nfor (int a = 0, b = 1; a < 2; a++, b += a) { total += b; }\nxs[i] = total;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-while-break",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nint n = 0;\nwhile (true) { n++; if (n > 3) { break; } }\nxs[i] = n;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-if-else-chain",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nif (xs[i] < 2) { xs[i] = 0; } else if (xs[i] < 3) { xs[i] = 1; } else { xs[i] = 2; }\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-checked-division",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = (xs[i] / 2) % 3;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-float-division",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfs[i] = fs[i] / 2.0;\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-mixed-arithmetic",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfs[i] = fs[i] * i + 1;\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-compound-updates",
        "@gpu void k(int[] xs, bool toggle) {\nint i = gpu_id();\nint shift = 1;\nbool flag = toggle;\nxs[i] <<= shift;\nflag ^= true;\nxs[i] /= 2;\nxs[i] %= 3;\nxs[i] += 1;\nxs[i]++;\nxs[i]--;\n}\nint main() { int[] xs = {8}; k(xs, true); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-float-updates",
        "@gpu void k(float[] fs) {\nint i = gpu_id();\nfloat f = fs[i];\nf++;\nf *= 2.0;\nf /= 3.0;\nfs[i] = f;\n}\nint main() { float[] fs = {1.0, 2.0, 3.0, 4.0}; k(fs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-bitwise-shift",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = ((xs[i] & 3) | (i ^ 1)) << 2 >> 1;\nxs[i] = ~xs[i];\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-bool-ops",
        "@gpu void k(int[] xs, bool flag) {\nint i = gpu_id();\nbool b = !flag || (i > 1 && xs[i] != 0);\nbool c = b != flag;\nif (c) { xs[i] = 1; }\n}\nint main() { int[] xs = {1, 2}; k(xs, false); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-casts",
        "@gpu void k(float[] fs, int[] xs) {\nint i = gpu_id();\nfs[i] = (float)xs[i] + (float)(bool)xs[i];\nxs[i] = (int)fs[i];\n}\nint main() { float[] fs = {1.0, 2.0}; int[] xs = {3, 4}; k(fs, xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-array-return",
        "@gpu int[] k(int[] xs) {\nint i = gpu_id();\nreturn xs[i] * 2;\n}\nint main() { int[] xs = {1, 2}; int[] ys = k(xs); return ys[0] - 2; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-array-return-buffer",
        "@gpu float[] k(float[] fs) {\nreturn fs;\n}\nint main() { float[] fs = {1.0, 2.0}; float[] gs = k(fs); return (int)gs[0] - 1; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-array-return-mixed",
        "@gpu float[] k(int[] xs, float scale) {\nint i = gpu_id();\nreturn xs[i] * scale;\n}\nint main() { int[] xs = {1, 2}; float[] fs = k(xs, 0.5); return (int)fs[1] - 1; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-negative-literal",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nxs[i] = -2147483648 + -xs[i] + +1;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-nested-scopes",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nint a = 1;\nif (a > 0) { int b = a + 1; xs[i] = b; }\nfor (int a2 = 0; a2 < 2; a2++) { int b = a2; xs[i] += b; }\nif (a > 0) { int b = 7; xs[i] -= b; }\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-bool-uniform-ternary",
        "@gpu void k(float[] fs, bool flag, float bias) {\nint i = gpu_id();\nfs[i] = flag ? fs[i] + bias : fs[i] - bias;\n}\nint main() { float[] fs = {1.0}; k(fs, true, 0.5); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-two-kernels",
        "@gpu void a(int[] xs) { int i = gpu_id(); xs[i] = xs[i] + 1; }\n@gpu void b(int[] xs, float[] fs) { int i = gpu_id(); fs[i] = xs[i] * 1.5; }\nint main() { int[] xs = {1}; float[] fs = {0.0}; a(xs); b(xs, fs); return 0; }\n",
        kernels=("a", "b"),
    ),
    GpuProbe(
        "valid-early-return",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nif (i >= 2) { return; }\nxs[i] = 0;\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-var-float-literal",
        "@gpu void k(float[] fs, int[] xs) {\nint i = gpu_id();\nvar a = 0.5 * 2;\nvar b = xs[i] > 1 ? 1 : 2.5;\nvar c = sqrt(fs[i]);\nfs[i] = a + b + c;\n}\nint main() { float[] fs = {4.0}; int[] xs = {2}; k(fs, xs); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-var-float-forms",
        "@gpu void k(float[] fs, bool c) {\nint i = gpu_id();\nvar a = 1.5;\nvar b = fs[i] * 0.5;\nvar d = -1.0;\nvar e = abs(2.0);\nvar f = c ? 1.0 : 2.0;\nvar g = 1.5f;\nfs[i] = a + b + d + e + f + g;\n}\nint main() { float[] fs = {4.0}; k(fs, true); return 0; }\n",
        kernels=("k",),
    ),
    GpuProbe(
        "valid-for-expr-init",
        "@gpu void k(int[] xs) {\nint i = gpu_id();\nint j = 0;\nfor (j = 1; j < 3; j += 1) { xs[i] += j; }\n}\nint main() { int[] xs = {1, 2, 3, 4}; k(xs); return 0; }\n",
        kernels=("k",),
    ),
)


class GpuParityHarness:
    """Compile one program through both compilers and reduce each run to an outcome."""

    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    def compile_probe(self, probe: GpuProbe) -> tuple[GpuOutcome, GpuOutcome]:
        source = self._workspace / "probe.btrc"
        source.write_text(probe.source)
        return self.compile_both(source, "--no-stdlib")

    def compile_both(self, source: Path, *flags: str) -> tuple[GpuOutcome, GpuOutcome]:
        return self._reference(source, flags), self._selfhost(source, flags)

    def _reference(self, source: Path, flags: tuple[str, ...]) -> GpuOutcome:
        generated = self._workspace / "reference.c"
        result = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-cache", *flags]
            + ["-o", str(generated)],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={**os.environ, "BTRC_CACHE_DIR": str(self._workspace / "reference-cache")},
            timeout=120,
        )
        if result.returncode == 0:
            return GpuOutcome(0, None, self._shaders(generated.read_text()))
        return GpuOutcome(result.returncode, self._diagnostic(REFERENCE_DIAGNOSTIC, result.stderr), ())

    def _selfhost(self, source: Path, flags: tuple[str, ...]) -> GpuOutcome:
        result = subprocess.run(
            [str(self._btrcc), *flags, str(source)], cwd=REPO, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return GpuOutcome(0, None, self._shaders(result.stdout))
        return GpuOutcome(result.returncode, self._diagnostic(SELFHOST_DIAGNOSTIC, result.stderr), ())

    @staticmethod
    def _diagnostic(pattern: re.Pattern[str], stderr: str) -> GpuDiagnostic:
        match = pattern.search(stderr)
        assert match is not None, stderr
        return GpuDiagnostic(match.group(1), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def _shaders(generated: str) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((match.group(1), ast.literal_eval(match.group(2))) for match in SHADER.finditer(generated)))

    @staticmethod
    def assert_naga_accepts(shaders: tuple[tuple[str, str], ...]) -> None:
        if NAGA is None:
            return
        for name, shader in shaders:
            validated = subprocess.run(
                [NAGA, "--stdin-file-path", f"{name}.wgsl"], input=shader, capture_output=True, text=True, timeout=60
            )
            assert validated.returncode == 0, f"{name}: {validated.stderr}"


@pytest.fixture
def harness(immutable_btrcc: Path, tmp_path: Path) -> GpuParityHarness:
    return GpuParityHarness(immutable_btrcc, tmp_path)


@pytest.mark.parametrize("probe", INVALID_PROBES, ids=lambda probe: probe.name)
def test_invalid_gpu_probe_reports_one_diagnostic_in_both_compilers(harness: GpuParityHarness, probe: GpuProbe) -> None:
    reference, selfhost = harness.compile_probe(probe)

    assert selfhost == reference
    assert reference.returncode == 1
    assert reference.diagnostic == probe.diagnostic


@pytest.mark.parametrize("probe", VALID_PROBES, ids=lambda probe: probe.name)
def test_valid_gpu_probe_emits_identical_validated_wgsl(harness: GpuParityHarness, probe: GpuProbe) -> None:
    reference, selfhost = harness.compile_probe(probe)

    assert reference.returncode == 0 and selfhost.returncode == 0
    assert selfhost.shaders == reference.shaders
    assert tuple(name for name, _ in reference.shaders) == probe.kernels
    harness.assert_naga_accepts(reference.shaders)


@pytest.mark.parametrize("program", CORPUS, ids=lambda program: program.stem)
def test_gpu_corpus_kernels_emit_identical_validated_wgsl(harness: GpuParityHarness, program: Path) -> None:
    reference, selfhost = harness.compile_both(program, "--no-dce")

    assert reference.returncode == 0 and selfhost.returncode == 0
    assert selfhost.shaders == reference.shaders
    harness.assert_naga_accepts(reference.shaders)


def test_probe_battery_covers_both_outcomes_and_unreachable_kernels() -> None:
    names = [probe.name for probe in INVALID_PROBES + VALID_PROBES]
    assert len(names) == len(set(names))
    assert all(probe.diagnostic is not None and not probe.kernels for probe in INVALID_PROBES)
    assert all(probe.diagnostic is None and probe.kernels for probe in VALID_PROBES if probe.name != "valid-unused")
    unreachable = [probe for probe in INVALID_PROBES if probe.source.rstrip().endswith(UNREACHABLE_MAIN)]
    assert len(INVALID_PROBES) >= 40 and len(VALID_PROBES) >= 20 and len(unreachable) >= 40
