"""Compile self-contained snippets through btrcc and the reference compiler, then build them as strict C11."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.tests.c_toolchains import configured_c_compiler

REPO = Path(__file__).resolve().parents[3]


CC = configured_c_compiler()


def run_in_repo(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


def compile_source(
    compiler: Path,
    tmp_path: Path,
    source: str,
    *,
    no_stdlib: bool = True,
    no_dce: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / "program.btrc"
    generated = tmp_path / "program.c"
    program.write_text(source)
    command = [str(compiler)]
    if no_stdlib:
        command.append("--no-stdlib")
    if no_dce:
        command.append("--no-dce")
    command.append(str(program))
    result = run_in_repo(command, timeout=120 if not no_stdlib else 30)
    if result.returncode == 0:
        generated.write_text(result.stdout)
    return result, generated


def compile_reference_source(
    tmp_path: Path,
    source: str,
    *,
    no_dce: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / "reference.btrc"
    generated = tmp_path / "reference.c"
    program.write_text(source)
    command = [
        sys.executable,
        "-m",
        "src.compiler.python.main",
        str(program),
        "--no-stdlib",
        "--no-cache",
    ]
    if no_dce:
        command.append("--no-dce")
    command.extend(["-o", str(generated)])
    result = run_in_repo(
        command,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "reference-cache")},
        timeout=120,
    )
    return result, generated


def strict_build_and_run(
    generated: Path,
    output: Path,
    *,
    optimization: str | None = None,
) -> None:
    optimization_flags = [optimization] if optimization is not None else []
    build = run_in_repo(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *optimization_flags,
            str(generated),
            "-o",
            str(output),
            "-lm",
            "-lpthread",
        ],
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = run_in_repo([str(output)], timeout=30)
    assert run.returncode == 0, run.stderr
