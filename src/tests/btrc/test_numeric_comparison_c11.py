"""Self-hosted strict-C parity for mixed numeric comparisons."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
)
from src.tests.python.test_numeric_comparison_c11 import RUNTIME_SOURCE

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def test_selfhost_mixed_comparisons_compile_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        RUNTIME_SOURCE,
    )
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "(left == right)" in emitted
    assert "(low < high)" in emitted

    for compiler in COMPILERS:
        executable = tmp_path / f"comparison-{Path(compiler).name}"
        compiled = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                str(generated),
                "-lm",
                "-lpthread",
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert compiled.returncode == 0, compiled.stderr
        run = subprocess.run(
            [str(executable)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout == "PASS: numeric comparison C11\n"


def test_selfhost_abi_dependent_mixed_comparison_still_fails_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, _ = _compile_source(
        semantic_btrcc,
        tmp_path,
        "int main() { size_t value = 1; return value < 2; }",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "mixes ABI-dependent integer type" in result.stderr
