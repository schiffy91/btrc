"""Strict dual-compiler harness for implicit string conversion contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
)
from src.tests.btrc.test_mutex_value_contract import _compile_pair
from src.tests.btrc.test_semantic_validation import REPO, _compile_source


def compile_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    name: str,
    *,
    include_stdlib: bool,
) -> tuple[tuple[str, Path], tuple[str, Path]]:
    """Compile one source through both production frontends."""
    if not include_stdlib:
        return _compile_pair(semantic_btrcc, tmp_path, source, name)

    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
        no_stdlib=False,
    )
    program = tmp_path / f"{name}.reference.btrc"
    reference_c = tmp_path / f"{name}.reference.c"
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
            "BTRC_CACHE_DIR": str(tmp_path / f"cache-{name}"),
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return ("selfhost", selfhost_c), ("reference", reference_c)


def assert_tracked_strict_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    *,
    include_stdlib: bool = False,
    expected_stdout: str | None = None,
) -> None:
    """Compile and execute a fixture under strict GCC and Clang."""
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
        include_stdlib=include_stdlib,
    )
    for artifact in compiled:
        _tracked_strict_matrix(
            artifact,
            tmp_path,
            expected_stdout=expected_stdout,
        )


__all__ = ["assert_tracked_strict_pair", "compile_pair"]
