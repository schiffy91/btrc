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


@dataclass(frozen=True)
class ParityOutcome:
    """What one compiler observably did with one program."""

    returncode: int
    diagnostic: GpuDiagnostic | None
    generated: str = ""


def _main(body: str) -> str:
    return "int main() { " + body + " }\n"


# Minimal collections for probes that need the classes a literal becomes,
# declared in the probe so its line numbers stay its own.
COLLECTIONS = (
    "class Map<K, V> { public void put(K key, V value) { } }\nclass Vector<T> { public void push(T value) { } }\n"
)
ANIMALS = (
    "class Animal { public int legs; public Animal(int legs) { self.legs = legs; } }\n"
    "class Dog extends Animal { public Dog() { self.legs = 4; } }\n"
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
    # A literal names no symbol, but an inferred binding or a for-in iterable
    # materializes it as a collection some module must declare.
    ParityProbe(
        "list-literal-for-in-without-vector",
        "int main() {\n\tint total = 0;\n\tfor x in [1, 2, 3] {\n\t\ttotal += x;\n\t}\n\treturn total;\n}\n",
        GpuDiagnostic("List literal needs the Vector class; add 'import Library.Vector;'", 3, 11),
    ),
    ParityProbe(
        "list-literal-parallel-for-without-vector",
        "int main() {\n\tparallel for x in [1, 2, 3] {\n\t\tint y = x;\n\t}\n\treturn 0;\n}\n",
        GpuDiagnostic("List literal needs the Vector class; add 'import Library.Vector;'", 2, 20),
    ),
    ParityProbe(
        "list-literal-var-without-vector",
        "int main() {\n\tvar values = [1, 2, 3];\n\treturn 0;\n}\n",
        GpuDiagnostic("List literal needs the Vector class; add 'import Library.Vector;'", 2, 15),
    ),
    # An unresolved element is the cause, so both report it, not the literal.
    ParityProbe(
        "list-literal-var-unresolved-element-without-vector",
        "int main() {\n\tvar values = [missing];\n\treturn 0;\n}\n",
        GpuDiagnostic("Unresolved identifier 'missing' used as a value", 2, 16),
    ),
    ParityProbe(
        "list-literal-for-in-unresolved-element-without-vector",
        "int main() {\n\tfor x in [missing] {\n\t\tint y = x;\n\t}\n\treturn 0;\n}\n",
        GpuDiagnostic("Unresolved identifier 'missing' used as a value", 2, 12),
    ),
    ParityProbe(
        "map-literal-for-in-without-map",
        'int main() {\n\tint total = 0;\n\tfor key in {"a": 1} {\n\t\ttotal += 1;\n\t}\n\treturn total;\n}\n',
        GpuDiagnostic("Map literal needs the Map class; add 'import Library.Map;'", 3, 13),
    ),
    ParityProbe(
        "map-literal-var-without-map",
        'int main() {\n\tvar counts = {"a": 1};\n\treturn 0;\n}\n',
        GpuDiagnostic("Map literal needs the Map class; add 'import Library.Map;'", 2, 15),
    ),
    # An inferred list or map literal takes its type from its first element or
    # entry; a later one that does not fit it is rejected where it stands.
    ParityProbe(
        "map-literal-var-mixed-values",
        COLLECTIONS + 'int main() {\n\tvar m = {"a": 1, "b": "two"};\n\treturn 0;\n}\n',
        GpuDiagnostic("Map value 1 has type 'string' but expected 'int'", 4, 24),
    ),
    ParityProbe(
        "map-literal-var-mixed-keys",
        COLLECTIONS + 'int main() {\n\tvar m = {"a": 1, 2: 3};\n\treturn 0;\n}\n',
        GpuDiagnostic("Map key 1 has type 'int' but expected 'string'", 4, 19),
    ),
    ParityProbe(
        "map-literal-var-subclass-first",
        COLLECTIONS + ANIMALS + 'int main() {\n\tvar m = {"dog": Dog(), "bird": Animal(2)};\n\treturn 0;\n}\n',
        GpuDiagnostic("Map value 1 has type 'Animal' but expected 'Dog'", 6, 33),
    ),
    ParityProbe(
        "map-literal-for-in-mixed-values",
        COLLECTIONS + 'int main() {\n\tfor key in {"a": 1, "b": "two"} {\n\t\tint y = 1;\n\t}\n\treturn 0;\n}\n',
        GpuDiagnostic("Map value 1 has type 'string' but expected 'int'", 4, 27),
    ),
    ParityProbe(
        "list-literal-var-mixed-elements",
        COLLECTIONS + 'int main() {\n\tvar values = [1, "two"];\n\treturn 0;\n}\n',
        GpuDiagnostic("List element 1 has type 'string' but expected 'int'", 4, 19),
    ),
    ParityProbe(
        "declared-map-mixed-values",
        COLLECTIONS + 'int main() {\n\tMap<string, int> m = {"a": 1, "b": "two"};\n\treturn 0;\n}\n',
        GpuDiagnostic("Initializer for 'm' value expects 'int' elements but got 'string'", 4, 37),
    ),
    # A global's initializer runs before main; a collection literal allocates.
    ParityProbe(
        "global-map-literal-var",
        COLLECTIONS + 'var counts = {"a": 1};\nint main() {\n\treturn 0;\n}\n',
        GpuDiagnostic("Global 'counts' requires a C constant/address initializer for static storage", 3, 1),
    ),
    ParityProbe(
        "global-map-literal-var-used",
        COLLECTIONS + 'var counts = {"a": 1};\nint main() {\n\tcounts.put("b", 2);\n\treturn 0;\n}\n',
        GpuDiagnostic("Global 'counts' requires a C constant/address initializer for static storage", 3, 1),
    ),
    ParityProbe(
        "global-list-literal-var",
        COLLECTIONS + "var values = [1, 2];\nint main() {\n\treturn 0;\n}\n",
        GpuDiagnostic("Global 'values' requires a C constant/address initializer for static storage", 3, 1),
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
)


class ParityHarness:
    """Compile one program through both compilers and reduce each run to an outcome."""

    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    def compile_probe(self, probe: ParityProbe, *flags: str) -> tuple[ParityOutcome, ParityOutcome]:
        source = self._workspace / "probe.btrc"
        source.write_text(probe.source)
        return self._reference(source, flags), self._selfhost(source, flags)

    def _reference(self, source: Path, flags: tuple[str, ...]) -> ParityOutcome:
        generated = self._workspace / "reference.c"
        result = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-cache", "--no-stdlib", *flags]
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
            [str(self._btrcc), "--no-stdlib", *flags, str(source)],
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

    assert selfhost == reference
    assert reference.returncode == 1
    assert reference.diagnostic == probe.diagnostic


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


def test_probe_battery_covers_both_outcomes() -> None:
    names = [probe.name for probe in INVALID_PROBES + VALID_PROBES]
    assert len(names) == len(set(names))
    assert all(probe.diagnostic is not None for probe in INVALID_PROBES)
    assert all(probe.diagnostic is None for probe in VALID_PROBES)
