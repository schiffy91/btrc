"""Runtime regressions for self-hosted managed-value owner state."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.tests.btrc.test_semantic_validation import _strict_build_and_run

REPO = Path(__file__).resolve().parents[3]
FIXTURE = (
    REPO
    / "src/tests/btrc/fixtures/selfhost_managed_owner_runtime.btrc"
)


def test_owner_queries_reuse_and_duplicate_cleanup_validation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = tmp_path / "selfhost-managed-owner-runtime.c"
    compile_result = subprocess.run(
        [
            str(semantic_btrcc),
            "--strict-imports",
            str(FIXTURE),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    generated.write_text(compile_result.stdout)

    executable = tmp_path / "selfhost-managed-owner-runtime"
    _strict_build_and_run(generated, executable, optimization="-O2")

    duplicate = subprocess.run(
        [str(executable), "duplicate"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert duplicate.returncode != 0
    assert "cleanup slot is registered more than once" in duplicate.stderr

    mismatch = subprocess.run(
        [str(executable), "mismatched", "metadata"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert mismatch.returncode != 0
    assert (
        "cleanup registration metadata does not match its declaration"
        in mismatch.stderr
    )
