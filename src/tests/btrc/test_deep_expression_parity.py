"""Deeply nested expressions compile in both compilers, or fail cleanly.

Every compiler stage walks an expression recursively, so nesting depth costs
stack. ``btrcc`` once ran on the main thread's 8 MiB stack and segfaulted while
lowering a left-associative chain of about 950 terms; it now runs its pipeline
on a 512 MiB thread (``BtrccCompilerStack``). The reference compiler's budget is
its recursion limit, and past it the compiler reports a diagnostic instead of a
traceback. Each program is generated here, at depths the old stack could not
reach, and must produce the same C through both compilers. The emitted C nests
as deeply as the source, past what some host C compilers accept (macOS clang
crashes on 2,000 nested parentheses), so the C is built and run at a depth
every host compiler handles.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import strict_build_and_run
from src.tests.process_limits import TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

DEPTH = 2000
RUN_DEPTH = 200
TOO_DEEP_DIAGNOSTIC = "error: expression or declaration nested too deeply to compile"


def _program(expression: str) -> str:
    return "int main() {\n\tint k = 1;\n\tint total = " + expression + ";\n\tprint(total);\n\treturn 0;\n}\n"


def _left_chain(terms: int) -> str:
    return " + ".join(["k"] * terms)


def _right_nested(terms: int) -> str:
    return "k + (" * (terms - 1) + "k" + ")" * (terms - 1)


def _reference(source: Path, output: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-stdlib", "--no-cache", "-o", str(output)],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "reference-cache")},
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )


def _selfhost(btrcc: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(btrcc), "--no-stdlib", str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )


SHAPES = [("left-chain", _left_chain), ("right-nested", _right_nested)]


def _compile_both(btrcc: Path, tmp_path: Path, shape: str, source_text: str) -> str:
    source = tmp_path / "Deep.btrc"
    source.write_text(source_text)
    reference_c = tmp_path / "reference.c"

    selfhost = _selfhost(btrcc, source)
    reference = _reference(source, reference_c, tmp_path)

    assert selfhost.returncode == 0, f"{shape}: btrcc exited {selfhost.returncode}: {selfhost.stderr[-2000:]}"
    assert reference.returncode == 0, f"{shape}: {reference.stderr[-2000:]}"
    assert selfhost.stdout == reference_c.read_text(), f"{shape}: the compilers' C diverged"
    return selfhost.stdout


@pytest.mark.parametrize(("shape", "expression"), SHAPES)
def test_deep_expression_compiles_identically_in_both_compilers(
    immutable_btrcc: Path, tmp_path: Path, shape: str, expression
) -> None:
    _compile_both(immutable_btrcc, tmp_path, shape, _program(expression(DEPTH)))


@pytest.mark.parametrize(("shape", "expression"), SHAPES)
def test_nested_expression_runs_with_its_value(immutable_btrcc: Path, tmp_path: Path, shape: str, expression) -> None:
    generated = tmp_path / "selfhost.c"
    generated.write_text(_compile_both(immutable_btrcc, tmp_path, shape, _program(expression(RUN_DEPTH))))
    strict_build_and_run(generated, tmp_path / "nested")
    run = subprocess.run([str(tmp_path / "nested")], capture_output=True, text=True, timeout=30)
    assert run.stdout == f"{RUN_DEPTH}\n"


def test_reference_compiler_reports_exhausted_recursion_as_a_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "TooDeep.btrc"
    source.write_text(_program(_left_chain(20000)))

    reference = _reference(source, tmp_path / "reference.c", tmp_path)

    assert reference.returncode == 1
    assert reference.stderr.strip() == TOO_DEEP_DIAGNOSTIC
    assert "Traceback" not in reference.stderr
