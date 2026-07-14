"""Shared dual-frontend harness for stdlib collection teardown contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.tests.btrc.test_mutex_value_contract import REPO, _strict_matrix
from src.tests.btrc.test_semantic_validation import _compile_source


def compile_stdlib_pair(
    semantic_btrcc: Path,
    output: Path,
    fixture: Path,
) -> tuple[tuple[str, Path], ...]:
    """Compile one stdlib-backed fixture through both production frontends."""
    source = fixture.read_text()
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        output,
        source,
        no_stdlib=False,
    )

    program = output / f"{fixture.stem}.reference.btrc"
    reference_c = output / f"{fixture.stem}.reference.c"
    program.write_text(source)
    reference = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-cache",
            "-o",
            str(reference_c),
        ],
        cwd=REPO,
        env={
            **os.environ,
            "BTRC_CACHE_DIR": str(output / "reference-cache"),
        },
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return ("selfhost", selfhost_c), ("reference", reference_c)


def run_strict_matrix(
    artifacts: tuple[tuple[str, Path], ...],
    output: Path,
) -> None:
    """Build and execute both frontend outputs with every strict C compiler."""
    for artifact in artifacts:
        _strict_matrix(artifact, output)


__all__ = ["compile_stdlib_pair", "run_strict_matrix"]
