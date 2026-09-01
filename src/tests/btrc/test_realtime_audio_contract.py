"""Managed realtime-audio callback and fatal lifecycle boundary parity."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).with_name("fixtures")
REALTIME_AUDIO = FIXTURES / "RealtimeAudioProgram.btrc"
CONSOLE_FATAL = FIXTURES / "ConsoleFatal.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _reference(source: Path, output: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=REPOSITORY,
        env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _selfhost(compiler: Path, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        [str(compiler), "--no-stdlib", str(source)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if compiled.returncode == 0:
        output.write_text(compiled.stdout)
    return compiled


def _strict_build(compiler: str, generated: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _compile_pair(
    semantic_btrcc: Path,
    source: Path,
    tmp_path: Path,
) -> dict[str, Path]:
    generated = {
        "reference": tmp_path / f"{source.stem}Reference.c",
        "selfhost": tmp_path / f"{source.stem}Selfhost.c",
    }
    reference = _reference(source, generated["reference"], tmp_path / f"{source.stem}-reference-cache")
    selfhost = _selfhost(semantic_btrcc, source, generated["selfhost"])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    return generated


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_realtime_audio_program_runs_from_both_frontends_with_strict_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _compile_pair(semantic_btrcc, REALTIME_AUDIO, tmp_path)
    for frontend, source in generated.items():
        emitted = source.read_text()
        assert "BorrowedClosure_OffsetProcess" in emitted
        assert "btrc_RealtimeAudioProgram" in emitted
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"RealtimeAudioProgram-{frontend}-{Path(compiler).name}"
            built = _strict_build(compiler, source, executable)
            assert built.returncode == 0, built.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert run.returncode == 0, run.stderr
            assert run.stdout == "PASS RealtimeAudioProgram\n"
            assert run.stderr == ""


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_console_fatal_flushes_one_diagnostic_and_aborts_from_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = _compile_pair(semantic_btrcc, CONSOLE_FATAL, tmp_path)
    for frontend, source in generated.items():
        emitted = source.read_text()
        assert "Console_fatal" in emitted
        assert "fflush(stderr)" in emitted
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"ConsoleFatal-{frontend}-{Path(compiler).name}"
            built = _strict_build(compiler, source, executable)
            assert built.returncode == 0, built.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert run.returncode != 0
            assert run.stdout == ""
            assert run.stderr == "fatal-contract\n"
