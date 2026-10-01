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

from src.tests.btrc.test_gpu_diagnostics_parity import REFERENCE_DIAGNOSTIC, SELFHOST_DIAGNOSTIC, GpuDiagnostic

REPO = Path(__file__).resolve().parents[3]
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
        "int main() {\n    int a = 1;\n\n    string s = f\"x {a} {a + nope}\";\n    return 0;\n}\n",
        GpuDiagnostic("Unresolved identifier 'nope' used as a value", 4, 29),
    ),
    ParityProbe(
        "fstring-parse-position",
        'int main() {\n  int a = 1;\n  string s = f"x {a} \\n {a +* 2}";\n  return 0;\n}\n',
        GpuDiagnostic("Unary operator '*' is not defined for 'int'", 3, 29),
    ),
)

VALID_PROBES = (
    ParityProbe("bool-xor", _main("bool b = true; bool flag = false; bool c = b ^ flag; return c ? 1 : 0;")),
    ParityProbe(
        "bool-bitwise-var",
        _main("bool b = true; bool flag = false; var c = b & flag | b; bool d = c; return d ? 0 : 1;"),
    ),
    ParityProbe(
        "bool-compound", _main("bool b = true; bool flag = false; b ^= flag; b &= true; return b ? 0 : 1;")
    ),
    ParityProbe("float-literal-double", _main("var x = 1.5; double* p = &x; return 0;")),
    ParityProbe("float-arithmetic-widens", _main("float f = 1.5; var y = f * 2.0; double* p = &y; return 0;")),
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
