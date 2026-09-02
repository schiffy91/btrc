"""Strict optimization coverage for formatted-string allocation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO, _compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
pytestmark = pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")

FIXTURES = (
    (
        REPO / "src/tests/strings/test_fstring_basic.btrc",
        "x=42\nPASS: test_fstring_basic\n",
    ),
    (
        Path(__file__).with_name("fixtures") / "fstring_allocation_c11.btrc",
        "\nPASS: formatted string allocation is non-null\n",
    ),
)


@pytest.mark.parametrize(("fixture", "expected_stdout"), FIXTURES)
def test_fstring_allocation_is_warning_clean_after_optimization(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    expected_stdout: str,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for frontend, generated in compiled:
        for compiler in COMPILERS:
            for optimization in ("-O0", "-O1", "-O2"):
                output = tmp_path / f"{frontend}-{Path(compiler).name}-{optimization[1:]}"
                build = subprocess.run(
                    [
                        compiler,
                        "-std=c11",
                        "-pedantic-errors",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        optimization,
                        str(generated),
                        "-pthread",
                        "-lm",
                        "-o",
                        str(output),
                    ],
                    cwd=REPO,
                    env=os.environ,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                assert build.returncode == 0, build.stderr
                executed = subprocess.run(
                    [str(output)],
                    cwd=REPO,
                    env=os.environ,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert executed.returncode == 0, executed.stderr
                assert executed.stdout == expected_stdout
