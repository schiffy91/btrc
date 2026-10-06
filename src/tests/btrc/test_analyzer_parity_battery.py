"""Both compilers accept and reject the same ordinary programs identically.

Each probe is compiled by the Python reference compiler and by the
self-hosted ``btrcc``. An invalid probe must fail in both with the same first
diagnostic -- identical message, line and column -- pinned below, so a
diagnostic reworded or reordered in one compiler alone fails here. A valid
probe must compile in both. The probes record analyzer, parser and emission
divergences the two compilers once had; ``@gpu`` kernels have their own
battery in ``test_gpu_diagnostics_parity.py``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import REFERENCE_DIAGNOSTIC, SELFHOST_DIAGNOSTIC, GpuDiagnostic

REPO = Path(__file__).resolve().parents[3]
INCLUDE = re.compile(r"^#include [<\"]([^>\"]+)[>\"]$", re.MULTILINE)
FUNCTION = re.compile(r"^static void (k__gpu(?:item|cpu))\([^)]*\) \{\n.*?^\}$", re.MULTILINE | re.DOTALL)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")


@dataclass(frozen=True)
class ParityProbe:
    """One source program and its pinned outcome: a first diagnostic, or acceptance."""

    name: str
    source: str
    diagnostic: GpuDiagnostic | None = None
    stdlib: bool = False


@dataclass(frozen=True)
class ParityOutcome:
    """What one compiler observably did with one program."""

    returncode: int
    diagnostic: GpuDiagnostic | None
    generated: str = ""


def _main(body: str) -> str:
    return "int main() { " + body + " }\n"


def _unbounded(generic: str, line: int, col: int) -> GpuDiagnostic:
    """A use that grows its own specialization's arguments (docs/language/translation-limits.md)."""
    return GpuDiagnostic(
        f"Generic {generic} grows its own type arguments through this use, so its specializations never end",
        line,
        col,
    )


def _fan(extras: tuple[str, ...]) -> str:
    """A generic class with one growing field per extra type: k growing uses."""
    fields = "".join(f"    public Fan<(T, {extra})>? f{index} = null;\n" for index, extra in enumerate(extras))
    return (
        "class Fan<T> {\n    public T value;\n" + fields + "    public Fan(T value) { self.value = value; }\n}\n"
        "int main() { Fan<int> f = new Fan<int>(1); return f.value; }\n"
    )


TUPLE_ARRAY = 'int main() {\n\t(int, string) w[2] = {(1, "a"), (2, "b")};\n'


def _self_specializing(name: str, field: str) -> str:
    """A generic class whose field needs a larger specialization of a generic."""
    return (
        f"class {name}<T> {{\n    public T value;\n    public {field} next = null;\n"
        f"    public {name}(T value) {{ self.value = value; }}\n}}\n"
        f"int main() {{ {name}<int> c = new {name}<int>(1); return c.value; }}\n"
    )


INVALID_PROBES = (
    ParityProbe(
        "coalesce-int",
        _main("int a = 1; int b = a ?? 2; return b;"),
        GpuDiagnostic("left operand of '??' must be a reference or optional-chain value; got 'int' and 'int'", 1, 33),
    ),
    ParityProbe(
        "float-shift",
        _main("float a = 1.0; float b = a << 2; return 0;"),
        GpuDiagnostic("Operator '<<' is not defined for 'float' and 'int'", 1, 39),
    ),
    ParityProbe(
        "bool-plus",
        _main("bool b = true; bool flag = false; bool c = b + flag; return 0;"),
        GpuDiagnostic("Operator '+' is not defined for 'bool' and 'bool'", 1, 57),
    ),
    ParityProbe(
        "bool-xor-is-not-int",
        _main("bool b = true; bool flag = false; string s = b ^ flag; return 0;"),
        GpuDiagnostic("Cannot assign 'bool' to variable 's' of type 'string'", 1, 48),
    ),
    ParityProbe(
        "index-scalar",
        _main("int a = 1; int b = a[0]; return b;"),
        GpuDiagnostic("Type 'int' is not indexable", 1, 33),
    ),
    ParityProbe(
        "call-non-callable-local",
        _main("int a = 1; int b = a(); return b;"),
        GpuDiagnostic("Resolved value 'a' of type 'int' is not callable", 1, 33),
    ),
    ParityProbe(
        "call-non-callable-expression",
        "int main() {\n  int[] xs = {1};\n  return xs[0]();\n}\n",
        GpuDiagnostic("Expression of type 'int' is not callable", 3, 10),
    ),
    ParityProbe(
        "unresolved-identifier",
        _main("int b = nope; return b;"),
        GpuDiagnostic("Unresolved identifier 'nope' used as a value", 1, 22),
    ),
    # An unknown ALL_CAPS spelling is not a C macro the compiler can see.
    ParityProbe(
        "unresolved-all-caps-constant",
        _main("int value = SOME_UNDECLARED_CONSTANT; return value;"),
        GpuDiagnostic("Unresolved identifier 'SOME_UNDECLARED_CONSTANT' used as a value", 1, 26),
    ),
    ParityProbe(
        "unresolved-enum-member-spelling",
        "enum Color { RED, GREEN };\nint main() { Color c = COLOR_BLUE; return 0; }\n",
        GpuDiagnostic("Unresolved identifier 'COLOR_BLUE' used as a value", 2, 24),
    ),
    # An unresolved name is reported before the inference error it causes.
    ParityProbe(
        "unresolved-var-initializer",
        _main("var a = UNKNOWN_X; return 0;"),
        GpuDiagnostic("Unresolved identifier 'UNKNOWN_X' used as a value", 1, 22),
    ),
    ParityProbe(
        "unresolved-var-operand",
        _main("var n = -UNKNOWN_X; return 0;"),
        GpuDiagnostic("Unresolved identifier 'UNKNOWN_X' used as a value", 1, 23),
    ),
    ParityProbe(
        "unresolved-var-enum-spelling",
        "enum E { A, B };\nint main() { var x = E_C; return 0; }\n",
        GpuDiagnostic("Unresolved identifier 'E_C' used as a value", 2, 22),
    ),
    ParityProbe(
        "generated-enum-symbol-var-initializer",
        "enum E { A, B };\nint main() { var x = E_A; return 0; }\n",
        GpuDiagnostic(
            "Source reference to compiler-generated C symbol 'E_A' for enum value 'E.A' is not allowed", 2, 22
        ),
    ),
    ParityProbe(
        "duplicate-function-definition",
        "int f() { return 1; }\nint f() { return 2; }\nint main() { return f(); }\n",
        GpuDiagnostic("Duplicate definition of function 'f'", 2, 1),
    ),
    ParityProbe(
        "conflicting-prototype",
        "int f(int a);\nint f() { return 2; }\nint main() { return f(); }\n",
        GpuDiagnostic("Conflicting declarations for function 'f'", 2, 1),
    ),
    ParityProbe(
        "conflicting-prototypes",
        "int f(int a);\nint f(long a);\nint main() { return 0; }\n",
        GpuDiagnostic("Conflicting declarations for function 'f'", 2, 1),
    ),
    ParityProbe(
        "class-and-function",
        "class f { public int x; }\nint f() { return 2; }\nint main() { return 0; }\n",
        GpuDiagnostic("Top-level name 'f' is declared as both class and function", 2, 5),
    ),
    ParityProbe(
        "global-and-function",
        "int f;\nint f() { return 2; }\nint main() { return f(); }\n",
        GpuDiagnostic("Top-level name 'f' is declared as both global and function", 2, 5),
    ),
    ParityProbe(
        "duplicate-class",
        "class C { public int x; }\nclass C { public int y; }\nint main() { return 0; }\n",
        GpuDiagnostic("Duplicate class name 'C'", 2, 7),
    ),
    ParityProbe(
        "duplicate-global",
        "int g = 1;\nint g = 2;\nint main() { return 0; }\n",
        GpuDiagnostic("Duplicate definition of global 'g'", 2, 1),
    ),
    ParityProbe(
        "assign-mismatch",
        _main('int a = 1; string s = "x"; a = s; return a;'),
        GpuDiagnostic("Cannot assign 'string' to 'int'", 1, 41),
    ),
    ParityProbe(
        "assign-class-mismatch",
        "class Box { public int v; }\nint main() { int[] xs = {1}; Box b = Box(); b = xs; return 0; }\n",
        GpuDiagnostic("Cannot assign 'int[]' to 'Box'", 2, 45),
    ),
    ParityProbe(
        "initializer-mismatch",
        _main('int a = "x"; return a;'),
        GpuDiagnostic("Cannot assign 'string' to variable 'a' of type 'int'", 1, 14),
    ),
    ParityProbe(
        "new-primitive",
        _main("int* p = new int(); return 0;"),
        GpuDiagnostic("new requires a class type, got 'int'", 1, 23),
    ),
    ParityProbe(
        "new-struct",
        "struct S { int x; };\nint main() { struct S* s = new S(); return 0; }\n",
        GpuDiagnostic("new requires a class type, got 'S'", 2, 28),
    ),
    ParityProbe(
        "new-pointer",
        "class C { public int x; }\nint main() { var c = new C*(); return 0; }\n",
        GpuDiagnostic("new requires an unqualified class type, got 'C*'", 2, 22),
    ),
    ParityProbe(
        "member-without-access",
        "class C { int x; }\nint main() { return 0; }\n",
        GpuDiagnostic("Expected access specifier (public/private/static), got 'int'", 1, 11),
    ),
    ParityProbe(
        "gpu-member-without-access",
        "class C { @gpu void k() }\nint main() { return 0; }\n",
        GpuDiagnostic("Expected access specifier (public/private/static), got '@gpu'", 1, 11),
    ),
    ParityProbe(
        "gpu-member-without-body",
        "class C { public @gpu void k() }\nint main() { return 0; }\n",
        GpuDiagnostic("Expected LBRACE, got RBRACE '}'", 1, 32),
    ),
    ParityProbe(
        "gpu-member",
        "class C { public @gpu void k(int[] xs) { int i = gpu_id(); } }\nint main() { return 0; }\n",
        GpuDiagnostic("@gpu is only supported on top-level functions; methods have no WGSL dispatch lowering", 1, 11),
    ),
    ParityProbe(
        "fstring-expression-position",
        'int main() {\n    int a = 1;\n\n    string s = f"x {a} {a + nope}";\n    return 0;\n}\n',
        GpuDiagnostic("Unresolved identifier 'nope' used as a value", 4, 29),
    ),
    ParityProbe(
        "fstring-parse-position",
        'int main() {\n  int a = 1;\n  string s = f"x {a} \\n {a +* 2}";\n  return 0;\n}\n',
        GpuDiagnostic("Unary operator '*' is not defined for 'int'", 3, 29),
    ),
    # Only a tuple VALUE is refused an index; an array, pointer or collection
    # whose element is a tuple indexes (tuples/TupleArrayIndexing.btrc).
    ParityProbe(
        "tuple-value-index",
        _main("(int, int) t = (1, 2); int a = t[0]; return a;"),
        GpuDiagnostic("Tuple values are not dynamically indexable; use ._N fields", 1, 45),
    ),
    ParityProbe(
        "tuple-value-index-store",
        _main("(int, int) t = (1, 2); t[1] = 3; return t._0;"),
        GpuDiagnostic("Tuple values are not dynamically indexable; use ._N fields", 1, 37),
    ),
    # An element of an array or pointer of tuples is a tuple: it is typed,
    # refused and checked as one in both compilers.
    ParityProbe(
        "tuple-array-element-to-int",
        TUPLE_ARRAY + "\tint bad = w[0];\n\treturn bad;\n}\n",
        GpuDiagnostic("Cannot assign 'Tuple<int, string>' to variable 'bad' of type 'int'", 3, 2),
    ),
    ParityProbe(
        "tuple-array-element-assign-int",
        TUPLE_ARRAY + "\tw[0] = 5;\n\treturn 0;\n}\n",
        GpuDiagnostic("Cannot assign 'int' to 'Tuple<int, string>'", 3, 2),
    ),
    ParityProbe(
        "tuple-array-element-wrong-tuple",
        TUPLE_ARRAY + '\tw[1] = ("a", 1);\n\treturn 0;\n}\n',
        GpuDiagnostic("Cannot assign 'Tuple<string, int>' to 'Tuple<int, string>'", 3, 2),
    ),
    ParityProbe(
        "tuple-array-element-field-range",
        TUPLE_ARRAY + "\tint bad = w[0]._5;\n\treturn bad;\n}\n",
        GpuDiagnostic("Tuple field '_5' is out of range for 2 element(s)", 3, 12),
    ),
    ParityProbe(
        "tuple-array-element-index",
        TUPLE_ARRAY + "\tint i = 0;\n\tint bad = w[i][1];\n\treturn bad;\n}\n",
        GpuDiagnostic("Tuple values are not dynamically indexable; use ._N fields", 4, 12),
    ),
    ParityProbe(
        "tuple-pointer-element-to-int",
        TUPLE_ARRAY + "\t(int, string)* p = w;\n\tint bad = p[0];\n\treturn bad;\n}\n",
        GpuDiagnostic("Cannot assign 'Tuple<int, string>' to variable 'bad' of type 'int'", 4, 2),
    ),
    ParityProbe(
        "tuple-array-element-return",
        "int first((int, string)* w) {\n\treturn w[1];\n}\nint main() { return 0; }\n",
        GpuDiagnostic("Return type mismatch: expected 'int' but got 'Tuple<int, string>'", 2, 2),
    ),
    # A lambda captures an array as a pointer, so sizeof would measure the
    # pointer; both compilers refuse it.
    ParityProbe(
        "sizeof-captured-array",
        "int main() {\n\tint captured[9];\n\tcaptured[0] = 1;\n"
        "\tvar measure = () => (int)(sizeof(captured) / sizeof(int));\n\treturn measure();\n}\n",
        GpuDiagnostic(
            "sizeof cannot measure array 'captured' inside a lambda, which captures it as a pointer; "
            "measure it outside the lambda",
            4,
            35,
        ),
    ),
    # Polymorphic recursion: each specialization needs a larger one, so
    # monomorphization never ends. Both compilers refuse the use that grows
    # its own derivation's arguments, once, after a few steps.
    ParityProbe(
        "generic-tuple-recursion",
        _self_specializing("Chain", "Chain<(T, int)>?"),
        _unbounded("class 'Chain'", 3, 12),
    ),
    ParityProbe(
        "generic-vector-recursion",
        "import Library.Vector;\n" + _self_specializing("Nest", "Nest<Vector<T>>?"),
        _unbounded("class 'Nest'", 4, 12),
        stdlib=True,
    ),
    ParityProbe(
        "generic-doubling-recursion",
        _self_specializing("Pair", "Pair<(T, T)>?"),
        _unbounded("class 'Pair'", 3, 12),
    ),
    ParityProbe(
        "generic-method-recursion",
        "class Walker {\n    public int count = 0;\n    public void walk<U>(U item, int depth) {\n"
        "        self.count = self.count + 1;\n"
        "        if (depth > 0) { self.walk((item, depth), depth - 1); }\n    }\n}\n"
        "int main() { Walker w = new Walker(); w.walk(1, 3); return w.count; }\n",
        _unbounded("method 'Walker.walk'", 5, 26),
    ),
    ParityProbe(
        "generic-mutual-recursion",
        "class Left<T> {\n    public T value;\n    public Right<(T, int)>? right = null;\n"
        "    public Left(T value) { self.value = value; }\n}\n"
        "class Right<T> {\n    public T value;\n    public Left<T>? left = null;\n"
        "    public Right(T value) { self.value = value; }\n}\n"
        "int main() { Left<int> l = new Left<int>(1); return l.value; }\n",
        _unbounded("class 'Right'", 3, 12),
    ),
    ParityProbe("generic-fan-of-three", _fan(("int", "long", "char")), _unbounded("class 'Fan'", 3, 12)),
    ParityProbe("generic-fan-of-four", _fan(("int", "long", "char", "short")), _unbounded("class 'Fan'", 3, 12)),
    ParityProbe(
        "generic-method-fan",
        "class Walker {\n    public int count = 0;\n    public void walk<U>(U item, int depth) {\n"
        "        self.count = self.count + 1;\n"
        "        if (depth > 0) { self.walk((item, depth), depth - 1); self.walk((depth, item), depth - 1); }\n"
        "    }\n}\n"
        "int main() { Walker w = new Walker(); w.walk(1, 3); return w.count; }\n",
        _unbounded("method 'Walker.walk'", 5, 26),
    ),
    # A class and a generic method that specialize each other: the cycle runs
    # through a method's own parameter, and its growing use is the call's.
    ParityProbe(
        "generic-class-method-cycle",
        "class Box<T> {\n    public T value;\n    public Box(T value) { self.value = value; }\n}\n"
        "class K<T> {\n    public T v;\n    public K(T v) { self.v = v; }\n    public void go(int d) {\n"
        "        if (d > 0) { Walker w = new Walker(); w.walk(new Box<T>(self.v), d - 1); }\n    }\n}\n"
        "class Walker {\n    public void walk<U>(U item, int d) {\n        K<U> k = new K<U>(item);\n"
        "        k.go(d);\n    }\n}\n"
        "int main() { Walker w = new Walker(); w.walk(1, 3); return 0; }\n",
        _unbounded("method 'Walker.walk'", 9, 47),
    ),
    # The refusal names the cycle's first growing use in source, whichever use
    # the compiler scans first: the declared type before the `new` expression.
    ParityProbe(
        "generic-growth-names-first-use",
        "class Box<T> {\n    public T value;\n    public Box(T value) { self.value = value; }\n"
        "    public int grow(int n) {\n"
        "        if (n > 0) { Box<(T, int)> b = new Box<(T, int)>((self.value, n)); return b.grow(n - 1); }\n"
        "        return 0;\n    }\n}\n"
        "int main() { Box<int> b = new Box<int>(1); return b.grow(2); }\n",
        _unbounded("class 'Box'", 5, 22),
    ),
    # Of two independent growing cycles, the first in source is named, not the
    # first instantiated.
    ParityProbe(
        "generic-two-growing-cycles",
        "class A<T> {\n    public T value;\n    public A<(T, int)>? a = null;\n"
        "    public A(T value) { self.value = value; }\n}\n"
        "class B<T> {\n    public T value;\n    public B<(int, T)>? b = null;\n"
        "    public B(T value) { self.value = value; }\n}\n"
        "int main() { B<int> b = new B<int>(1); A<int> a = new A<int>(1); return a.value + b.value; }\n",
        _unbounded("class 'A'", 3, 12),
    ),
    # A use the analyzer inferred has no source position; the written use is named.
    ParityProbe(
        "generic-growth-through-inferred-var",
        "class Box<T> {\n    public T value;\n    public Box(T value) { self.value = value; }\n"
        "    public int grow(int n) {\n"
        "        if (n > 0) { var b = new Box<(T, int)>((self.value, n)); return b.grow(n - 1); }\n"
        "        return 0;\n    }\n}\n"
        "int main() { Box<int> b = new Box<int>(1); return b.grow(2); }\n",
        _unbounded("class 'Box'", 5, 34),
    ),
    # A pointer level grows a specialization as a generic level does.
    ParityProbe(
        "generic-pointer-recursion",
        "class P<T> {\n    public T value;\n    public P<T*>? next = null;\n}\n"
        "int main() { P<int> x = new P<int>(); return 0; }\n",
        _unbounded("class 'P'", 3, 12),
    ),
)

VALID_PROBES = (
    # Hosted ABI macros and C11 predefined macros are the foreign constants
    # a file without an unmodeled include may name.
    ParityProbe("hosted-abi-macro", _main("int e = EOF; return e < 0 ? 0 : 1;")),
    ParityProbe("c11-predefined-macro", _main("int line = __LINE__; return line == 1 ? 0 : 1;")),
    ParityProbe("bool-xor", _main("bool b = true; bool flag = false; bool c = b ^ flag; return c ? 1 : 0;")),
    ParityProbe(
        "bool-bitwise-var",
        _main("bool b = true; bool flag = false; var c = b & flag | b; bool d = c; return d ? 0 : 1;"),
    ),
    ParityProbe("bool-compound", _main("bool b = true; bool flag = false; b ^= flag; b &= true; return b ? 0 : 1;")),
    ParityProbe("float-literal-double", _main("var x = 1.5; double* p = &x; return 0;")),
    ParityProbe("float-arithmetic-widens", _main("float f = 1.5; var y = f * 2.0; double* p = &y; return 0;")),
    ParityProbe("source-standard-include", "#include <assert.h>\n" + _main("assert(1 == 1); return 0;")),
    ParityProbe("tuple-array-element-var", TUPLE_ARRAY + "\tvar e = w[1];\n\treturn e._0;\n}\n"),
    # A fixed use inside a template starts a new derivation: E<T> holds a
    # C<Box<int>> that does not grow, so the specializations are finite.
    ParityProbe(
        "generic-fixed-use-in-cycle",
        "class Box<T> { public T value; }\nclass C<T> { public Box<T> b; public E<T> e; }\n"
        "class E<T> { public C<Box<int>> c; }\n" + _main("C<int> x = new C<int>(); return 0;"),
    ),
    ParityProbe(
        "generic-fixed-use-in-method-cycle",
        "class Box<T> { public T value; }\n"
        "class C<T> { public Box<T> b; public void go() { E<T> e = new E<T>(); e.run(); } }\n"
        "class E<T> { public void run() { C<Box<int>> c = new C<Box<int>>(); } }\n"
        + _main("C<int> x = new C<int>(); x.go(); return 0;"),
    ),
    # A cycle whose uses pass parameters bare is finite: A<T, U> reaches B<U>,
    # which reaches A<T, Box<int>>, a fixed argument, so nothing grows.
    ParityProbe(
        "generic-bare-two-class-cycle",
        "class Box<T> { public T value; }\nclass A<T, U> { public B<U>? b = null; }\n"
        "class B<T> { public A<T, Box<int>>? a = null; }\n" + _main("A<int, int> x = new A<int, int>(); return 0;"),
    ),
    # A generic method's uses hold only when the method is specialized: a
    # Box<(T, U)> in pair<U> does not make every Box<T> need a larger Box.
    ParityProbe(
        "generic-method-wraps-its-class",
        "class Box<T> {\n    public T value;\n    public Box(T value) { self.value = value; }\n"
        "    public Box<(T, U)>? pair<U>(U u) { return null; }\n"
        "    public int take<U>(U u) { Box<(T, U)>? x = null; return 0; }\n}\n"
        "int main() { Box<int> b = new Box<int>(1); var p = b.pair(2); return b.take(3); }\n",
    ),
    # A type the program writes out is not limited, however deep.
    ParityProbe(
        "generic-written-deep",
        "class Box<T> {\n    public T value;\n    public Box(T value) { self.value = value; }\n}\n"
        + _main("Box<Box<Box<Box<Box<Box<Box<Box<Box<int>>>>>>>>>? deep = null; return 0;"),
    ),
)


class ParityHarness:
    """Compile one program through both compilers and reduce each run to an outcome."""

    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    @property
    def btrcc(self) -> Path:
        return self._btrcc

    def compile_probe(self, probe: ParityProbe, *flags: str) -> tuple[ParityOutcome, ParityOutcome]:
        source = self._workspace / "probe.btrc"
        source.write_text(probe.source)
        if not probe.stdlib:
            flags = ("--no-stdlib", *flags)
        return self._reference(source, flags), self._selfhost(source, flags)

    def _reference(self, source: Path, flags: tuple[str, ...]) -> ParityOutcome:
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
            return ParityOutcome(0, None, generated.read_text())
        return ParityOutcome(result.returncode, self._diagnostic(REFERENCE_DIAGNOSTIC, result.stderr))

    def _selfhost(self, source: Path, flags: tuple[str, ...]) -> ParityOutcome:
        result = subprocess.run(
            [str(self._btrcc), *flags, str(source)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return ParityOutcome(0, None, result.stdout)
        return ParityOutcome(result.returncode, self._diagnostic(SELFHOST_DIAGNOSTIC, result.stderr))

    @staticmethod
    def _diagnostic(pattern: re.Pattern[str], stderr: str) -> GpuDiagnostic:
        match = pattern.search(stderr)
        assert match is not None, stderr
        return GpuDiagnostic(match.group(1), int(match.group(2)), int(match.group(3)))


@pytest.fixture
def harness(immutable_btrcc: Path, tmp_path: Path) -> ParityHarness:
    return ParityHarness(immutable_btrcc, tmp_path)


@pytest.mark.parametrize("probe", INVALID_PROBES, ids=lambda probe: probe.name)
def test_invalid_probe_reports_one_diagnostic_in_both_compilers(harness: ParityHarness, probe: ParityProbe) -> None:
    reference, selfhost = harness.compile_probe(probe)

    assert reference.returncode == 1
    assert reference.diagnostic == probe.diagnostic
    if probe.stdlib:
        # btrcc numbers lines across the prepended stdlib, so an importing
        # probe pins the reference line and compares message and column.
        assert selfhost.returncode == 1 and selfhost.diagnostic is not None
        assert (selfhost.diagnostic.message, selfhost.diagnostic.col) == (
            probe.diagnostic.message,
            probe.diagnostic.col,
        )
    else:
        assert selfhost == reference


@pytest.mark.parametrize("probe", VALID_PROBES, ids=lambda probe: probe.name)
def test_valid_probe_compiles_in_both_compilers(harness: ParityHarness, probe: ParityProbe) -> None:
    reference, selfhost = harness.compile_probe(probe)

    assert (reference.returncode, reference.diagnostic) == (0, None)
    assert (selfhost.returncode, selfhost.diagnostic) == (0, None)


def test_an_unmodeled_include_admits_its_macros_only_in_its_own_file(harness: ParityHarness, tmp_path: Path) -> None:
    """A raw quoted include of a C header the importer does not model is the
    explicit compatibility path for ALL_CAPS names; it covers the including
    file, never a module that file imports."""
    (tmp_path / "Local.h").write_text("#define LOCAL_LIMIT 7\n")
    (tmp_path / "Helper.btrc").write_text("int helperLimit() { return HELPER_LIMIT; }\n")
    admitted = ParityProbe("unmodeled-include", '#include "Local.h"\n' + _main("return LOCAL_LIMIT == 7 ? 0 : 1;"))
    reference, selfhost = harness.compile_probe(admitted)
    assert (reference.returncode, reference.diagnostic) == (0, None)
    assert (selfhost.returncode, selfhost.diagnostic) == (0, None)

    rejected = ParityProbe(
        "unmodeled-include-elsewhere",
        '#include "Local.h"\nimport ./Helper.btrc;\n' + _main("return helperLimit() == LOCAL_LIMIT ? 0 : 1;"),
    )
    reference, selfhost = harness.compile_probe(rejected)
    for outcome in (reference, selfhost):
        assert outcome.returncode != 0
        assert outcome.diagnostic is not None
        assert outcome.diagnostic.message == "Unresolved identifier 'HELPER_LIMIT' used as a value"


def test_source_include_of_a_standard_header_is_emitted_once(harness: ParityHarness) -> None:
    probe = next(probe for probe in VALID_PROBES if probe.name == "source-standard-include")
    reference, selfhost = harness.compile_probe(probe)

    for outcome in (reference, selfhost):
        headers = INCLUDE.findall(outcome.generated)
        assert headers.count("assert.h") == 1, headers
        assert len(headers) == len(set(headers)), headers


def test_gpu_float_division_cpu_fallback_matches_between_compilers(harness: ParityHarness) -> None:
    """Both WGSL emitters flag a zero float divisor; the CPU worker must do the same."""
    probe = ParityProbe(
        "gpu-float-division-fallback",
        "@gpu void k(float[] fs, float d) {\n    int i = gpu_id();\n    var half = 0.5;\n"
        "    fs[i] = fs[i] / d * half;\n}\n"
        "int main() { float[] fs = {1.0, -2.0}; k(fs, 0.0); return 0; }\n",
    )
    reference, selfhost = harness.compile_probe(probe)

    assert reference.returncode == 0 and selfhost.returncode == 0
    workers = []
    for outcome in (reference, selfhost):
        functions = {match.group(1): match.group(0) for match in FUNCTION.finditer(outcome.generated)}
        assert set(functions) == {"k__gpuitem", "k__gpucpu"}, outcome.generated
        item = functions["k__gpuitem"]
        # The kernel's `var` binds an f32 like its WGSL, and the division takes
        # the checked helper whose float overload reports "Division by zero".
        assert "float half = 0.5f;" in item
        assert "__btrc_div(" in item
        assert 'if (b == 0.0F) { fprintf(stderr, "Division by zero\\n"); exit(1); }' in outcome.generated
        workers.append(item)
    assert workers[0].count("__btrc_div(") == workers[1].count("__btrc_div(")


@pytest.mark.parametrize("name", ["generic-fan-of-three", "generic-fan-of-four", "generic-method-fan"])
def test_growing_specialization_ends_quickly_and_once(harness: ParityHarness, tmp_path: Path, name: str) -> None:
    """Refusal ends specialization after a few steps, however many uses grow,
    and the reference reports it once, as btrcc does."""
    probe = next(probe for probe in INVALID_PROBES if probe.name == name)
    started = time.monotonic()
    reference, selfhost = harness.compile_probe(probe)
    assert time.monotonic() - started < 20
    assert reference == selfhost
    source = tmp_path / "fan.btrc"
    source.write_text(probe.source)
    result = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-cache", "--no-stdlib"]
        + ["-o", str(tmp_path / "fan.c")],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.stderr.count("error:") == 1, result.stderr


def test_owned_store_into_a_tuple_array_element_is_refused_in_both(harness: ParityHarness, tmp_path: Path) -> None:
    """An f-string is a caller-owned temporary; a tuple element of an array is shallow."""
    source = tmp_path / "store.btrc"
    source.write_text(TUPLE_ARRAY + '\tw[0]._1 = f"{w[1]._0}!";\n\treturn 0;\n}\n')
    message = (
        "caller-owned temporary cannot be stored in a shallow aggregate; "
        "bind the owner to a local and store only its borrowed reference"
    )
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-cache", "--no-stdlib"]
        + ["-o", str(tmp_path / "store.c")],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    selfhost = subprocess.run(
        [str(harness.btrcc), "--no-stdlib", str(source)], cwd=REPO, capture_output=True, text=True, timeout=120
    )
    assert reference.returncode != 0 and message in reference.stderr, reference.stderr
    assert selfhost.returncode != 0 and message in selfhost.stderr, selfhost.stderr


def test_probe_battery_covers_both_outcomes() -> None:
    names = [probe.name for probe in INVALID_PROBES + VALID_PROBES]
    assert len(names) == len(set(names))
    assert all(probe.diagnostic is not None for probe in INVALID_PROBES)
    assert all(probe.diagnostic is None for probe in VALID_PROBES)
