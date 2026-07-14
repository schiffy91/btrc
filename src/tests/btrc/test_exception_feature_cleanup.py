"""Exception feature discovery must preserve module-wide ARC cleanup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO, _compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
LAMBDA_CONSTRUCTOR = FIXTURES / "lifecycle_lambda_constructor_abandon_runtime.btrc"
FREESTANDING_CLEANUP = FIXTURES / "lifecycle_freestanding_exception_cleanup_runtime.btrc"

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires a hosted C11 compiler",
)


def test_lambda_only_exceptions_abandon_constructors_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        LAMBDA_CONSTRUCTOR.read_text(),
        LAMBDA_CONSTRUCTOR.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)


def test_freestanding_exceptions_cleanup_across_calls_and_constructors(
    tmp_path: Path,
) -> None:
    source = tmp_path / FREESTANDING_CLEANUP.name
    generated = tmp_path / "freestanding_exception_cleanup.c"
    source.write_text(FREESTANDING_CLEANUP.read_text())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--freestanding",
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
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "btrc_rt.h").exists()
    assert "#define BTRC_RT_NEEDS_SETJMP 1" in generated.read_text()
    _tracked_strict_matrix(("freestanding", generated), tmp_path)
