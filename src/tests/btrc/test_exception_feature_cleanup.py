"""Exception feature discovery must preserve module-wide ARC cleanup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.allocation_tracking_harness import tracked_strict_matrix
from src.tests.btrc.dual_frontend_harness import REPO, compile_snippet_pair
from src.tests.c_toolchains import HOST_C_COMPILERS

FIXTURES = Path(__file__).with_name("fixtures")
LAMBDA_CONSTRUCTOR = FIXTURES / "LifecycleLambdaConstructorAbandonRuntime.btrc"
FREESTANDING_CLEANUP = FIXTURES / "LifecycleFreestandingExceptionCleanupRuntime.btrc"

pytestmark = pytest.mark.skipif(
    not HOST_C_COMPILERS,
    reason="requires a hosted C11 compiler",
)


def test_lambda_only_exceptions_abandon_constructors_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        LAMBDA_CONSTRUCTOR.read_text(),
        LAMBDA_CONSTRUCTOR.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)


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
    tracked_strict_matrix(("freestanding", generated), tmp_path)
