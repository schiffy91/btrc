"""Every example program transpiles through both compilers and behaves the same.

AGENTS.md promises that the examples prove the strict-import path on both
compilers. Each top-level ``examples/<name>/*.btrc`` entry is transpiled for
the host target by the Python reference compiler and by the self-hosted
``btrcc``. Examples that need no SDK, GPU runtime or display also compile
under strict C11 with every host compiler, from both compilers' C, and must
exit 0 with identical output. The rest (GUI, GPU, tray) only transpile here;
their Makefiles build them through the native plan on a host with those SDKs.

The two compilers' C is not byte-identical today (temporary naming, indexed
stores, runtime-helper selection and header order differ; see
docs/design/compiler-parity.md), so this compares behavior, as the corpus does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.frontend.packages import PackageTarget
from src.tests.c_toolchains import HOST_C_COMPILERS, requires_host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples"
ENTRIES = sorted(path.relative_to(REPO).as_posix() for path in EXAMPLES.glob("*/*.btrc"))
# Hosted programs with no SDK, GPU or display dependency.
RUNNABLE = frozenset(
    {
        "examples/callback/Main.btrc",
        "examples/realtime-primitives/Main.btrc",
        "examples/realtime-primitives/RealtimeGain.btrc",
        "examples/todo/Todo.btrc",
    }
)
STRICT_C11 = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror")
_HOST = PackageTarget.parse(None)
# btrcc requires an explicit target for native bindings; name the host for both.
HOST_TARGET = f"{_HOST.operating_system}-{_HOST.architecture}"


def _python_c(entry: str) -> str:
    source = (REPO / entry).read_text(encoding="utf-8")
    result = Compiler().compile(source, entry, CompilerOptions(use_cache=False, target=HOST_TARGET))
    assert result.failure is None, f"{entry}: {result.failure}"
    assert result.analyzed is None or not result.analyzed.errors, result.analyzed.errors
    assert result.c_source is not None, f"{entry}: the Python compiler emitted no C"
    # Examples analyze clean in both compilers, as the compiler itself does.
    assert [diagnostic.message for diagnostic in result.diagnostics if diagnostic.severity == "warning"] == []
    return result.c_source


def _selfhost_c(btrcc: str, entry: str) -> str:
    result = subprocess.run(
        [btrcc, "--no-cache", "--target", HOST_TARGET, entry],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert result.returncode == 0, f"{entry}: btrcc failed:\n{result.stderr[:2000]}"
    assert "warning:" not in result.stderr, result.stderr
    return result.stdout


def test_every_example_directory_has_an_entry() -> None:
    directories = {path.name for path in EXAMPLES.iterdir() if path.is_dir() and path.name != "native-package"}

    assert directories == {Path(entry).parts[1] for entry in ENTRIES}
    assert set(ENTRIES) >= RUNNABLE


@pytest.mark.parametrize("entry", ENTRIES)
def test_example_transpiles_through_both_compilers(btrcc_bin: str, entry: str) -> None:
    assert "int main" in _python_c(entry)
    assert "int main" in _selfhost_c(btrcc_bin, entry)


def _run_strict(generated: str, tmp_path: Path, label: str, compiler: str) -> str:
    source = tmp_path / f"{label}.c"
    source.write_text(generated, encoding="utf-8")
    executable = tmp_path / f"{label}-{Path(compiler).name}"
    built = subprocess.run(
        [compiler, *STRICT_C11, str(source), "-o", str(executable), "-lm", "-lpthread"],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, f"{label} with {compiler}:\n{built.stderr}"
    ran = subprocess.run([str(executable)], cwd=tmp_path, input="", capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, f"{label} with {compiler}:\n{ran.stdout}\n{ran.stderr}"
    return ran.stdout


@requires_host_c_compiler
@pytest.mark.parametrize("entry", sorted(RUNNABLE))
def test_sdk_free_example_runs_identically_under_strict_c11(btrcc_bin: str, tmp_path: Path, entry: str) -> None:
    generated = {"python": _python_c(entry), "selfhost": _selfhost_c(btrcc_bin, entry)}
    for compiler in HOST_C_COMPILERS:
        outputs = {label: _run_strict(text, tmp_path, label, compiler) for label, text in generated.items()}
        assert outputs["python"] == outputs["selfhost"], f"{entry} with {compiler}"
