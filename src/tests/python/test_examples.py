"""Every example program transpiles through both compilers to the same C.

AGENTS.md promises that the examples prove the strict-import path on both
compilers. Each top-level ``examples/<name>/*.btrc`` entry is transpiled by the
Python reference compiler and by the self-hosted ``btrcc``; the generated C
must be byte-identical. Examples that need no SDK, GPU runtime or display
also compile under strict C11 with every host compiler and run to a zero exit.
The rest (GUI, GPU, tray) only transpile here; their Makefiles build them
through the native plan on a host that has those SDKs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
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


def _python_c(entry: str) -> str:
    source = (REPO / entry).read_text(encoding="utf-8")
    result = Compiler().compile(source, entry, CompilerOptions(use_cache=False))
    assert result.failure is None, f"{entry}: {result.failure}"
    assert result.analyzed is None or not result.analyzed.errors, result.analyzed.errors
    assert result.c_source is not None, f"{entry}: the Python compiler emitted no C"
    return result.c_source


def _selfhost_c(btrcc: str, entry: str) -> str:
    result = subprocess.run(
        [btrcc, "--no-cache", entry],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert result.returncode == 0, f"{entry}: btrcc failed:\n{result.stderr[:2000]}"
    return result.stdout


def test_every_example_directory_has_an_entry() -> None:
    directories = {path.name for path in EXAMPLES.iterdir() if path.is_dir() and path.name != "native-package"}

    assert directories == {Path(entry).parts[1] for entry in ENTRIES}
    assert set(ENTRIES) >= RUNNABLE


@pytest.mark.parametrize("entry", ENTRIES)
def test_example_transpiles_identically_through_both_compilers(btrcc_bin: str, entry: str) -> None:
    assert _selfhost_c(btrcc_bin, entry) == _python_c(entry)


@requires_host_c_compiler
@pytest.mark.parametrize("entry", sorted(RUNNABLE))
def test_sdk_free_example_runs_under_strict_c11(tmp_path: Path, entry: str) -> None:
    generated = tmp_path / "example.c"
    generated.write_text(_python_c(entry), encoding="utf-8")
    for compiler in HOST_C_COMPILERS:
        executable = tmp_path / f"example-{Path(compiler).name}"
        built = subprocess.run(
            [compiler, *STRICT_C11, str(generated), "-o", str(executable), "-lm", "-lpthread"],
            capture_output=True,
            text=True,
            timeout=C_COMPILE_TIMEOUT,
        )
        assert built.returncode == 0, built.stderr
        ran = subprocess.run(
            [str(executable)],
            cwd=tmp_path,
            input="",
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        assert ran.returncode == 0, f"{entry} with {compiler}:\n{ran.stdout}\n{ran.stderr}"
