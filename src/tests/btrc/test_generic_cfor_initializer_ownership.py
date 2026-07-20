"""Strict Python-reference coverage for generic C-for initializer owners."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _compiler_environment,
)

REPO = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "generic_cfor_initializer_ownership_runtime.btrc"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires a strict C11 compiler",
)


def _generated_function(source: str, symbol: str) -> str:
    definition = re.search(
        rf"^static [^\n;]+\b{re.escape(symbol)}\([^;\n]*\) \{{$",
        source,
        re.MULTILINE,
    )
    assert definition is not None, symbol
    next_definition = re.search(
        r"^(?:static [^\n;]+\([^;\n]*\)|int main\(void\)) \{$",
        source[definition.end() :],
        re.MULTILINE,
    )
    end = definition.end() + next_definition.start() if next_definition is not None else len(source)
    return source[definition.start() : end]


def test_generic_cfor_initializer_owners_run_strictly(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generic-cfor.reference.c"
    compile_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(FIXTURE),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={
            **os.environ,
            "BTRC_CACHE_DIR": str(tmp_path / "cache"),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    emitted = generated.read_text()
    for method in (
        "zeroExit",
        "normalExit",
        "breakExit",
        "continueExit",
        "earlyReturn",
        "throwingExit",
        "conditionalDelete",
        "deleteShadow",
        "typeNameShadow",
    ):
        body = _generated_function(
            emitted,
            f"btrc_GenericCForHarness_int_{method}",
        )
        assert "for (;" in body
        assert "__btrc_scope_released" in body

    for compiler in COMPILERS:
        executable = tmp_path / f"generic-cfor-{Path(compiler).name}"
        build = subprocess.run(
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
                str(executable),
            ],
            cwd=REPO,
            env=_compiler_environment(compiler),
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run(
            [str(executable)],
            cwd=REPO,
            env=_compiler_environment(compiler),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stderr
