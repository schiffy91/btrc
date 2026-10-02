"""Library.TOML compiles warning-free whether plain char is signed or unsigned.

btrcc imports Library.TOML and is built with -Wextra -Werror; on aarch64 Linux
plain char is unsigned, where a `c >= 0` test is -Wtype-limits' "always true".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src/tests/stdlib/TomlUtilities.btrc"
C_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("toml-char-signedness")
    output = directory / "TomlUtilities.c"
    transpile = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(SOURCE), "-o", str(output)],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "BTRC_CACHE_DIR": str(directory / "cache")},
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert transpile.returncode == 0, transpile.stderr
    return output


@pytest.mark.skipif(not C_COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", C_COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("signedness", ["-fsigned-char", "-funsigned-char"])
def test_toml_builds_and_runs_with_either_char_signedness(generated, tmp_path, c_compiler, signedness):
    executable = tmp_path / "TomlUtilities"
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            signedness,
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert run.returncode == 0, run.stderr
    assert "PASS: test_stdlib_toml_utilities" in run.stdout
