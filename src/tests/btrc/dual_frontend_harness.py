"""Compile one snippet through both compilers and run each program on every host C compiler."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.tests.btrc.selfhost_snippet_harness import compile_source, strict_build_and_run
from src.tests.c_toolchains import HOST_C_COMPILERS

REPO = Path(__file__).resolve().parents[3]


def compile_reference_snippet(tmp_path: Path, source: str, name: str):
    program = tmp_path / f"{name}.btrc"
    generated = tmp_path / f"{name}.reference.c"
    program.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, generated


def compile_snippet_pair(semantic_btrcc, tmp_path, source, name):
    selfhost, selfhost_c = compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = compile_reference_snippet(
        tmp_path,
        source,
        name,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return ("selfhost", selfhost_c), ("reference", reference_c)


def build_and_run_strict(generated, output, compiler, extra_flags=()):
    environment = None
    if sys.platform == "darwin" and os.path.realpath(compiler) == "/usr/bin/clang":
        environment = {
            name: os.environ[name]
            for name in (
                "HOME",
                "USER",
                "LOGNAME",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
            )
            if name in os.environ
        }
        environment.update(
            {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "TMPDIR": "/tmp",
            }
        )
    build = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1" if extra_flags else "-O2",
            *extra_flags,
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(output),
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert build.returncode == 0, build.stderr
    run_environment = dict(os.environ if environment is None else environment)
    run_environment["TSAN_OPTIONS"] = "halt_on_error=1"
    run = subprocess.run(
        [str(output)],
        cwd=REPO,
        env=run_environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr


def strict_c11_matrix(compiled, tmp_path):
    for compiler in HOST_C_COMPILERS:
        output = tmp_path / f"{compiled[0]}-{Path(compiler).name}"
        build_and_run_strict(compiled[1], output, compiler)


def compile_ownership_reference(tmp_path: Path, source: str):
    program = tmp_path / "reference-Ownership.btrc"
    generated = tmp_path / "reference-ownership.c"
    program.write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, generated


def compile_both(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
):
    selfhost, selfhost_source = compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = compile_ownership_reference(
        tmp_path,
        source,
    )
    return (selfhost, selfhost_source), (reference, reference_source)


def strict_dual_frontend_runtime(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    stem: str,
) -> None:
    selfhost, selfhost_source = compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = compile_ownership_reference(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    strict_build_and_run(
        selfhost_source,
        tmp_path / f"selfhost-{stem}",
    )
    strict_build_and_run(
        reference_source,
        tmp_path / f"reference-{stem}",
    )


def strict_compile_and_run(
    source: Path,
    output: Path,
    c_compiler: str,
) -> None:
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(output)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 0, run.stderr
