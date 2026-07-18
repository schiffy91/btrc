"""Dual-frontend execution helpers for production-readiness contracts."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from src.tests.btrc.string_coercion_harness import compile_pair
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _compiler_environment,
    _tracked_strict_matrix,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

CompiledPair = tuple[tuple[str, Path], tuple[str, Path]]
OutputValidator = Callable[[str], None]


def compile_fixture_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    *,
    include_stdlib: bool = False,
) -> CompiledPair:
    """Compile one standalone fixture through both production frontends."""
    return compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
        include_stdlib=include_stdlib,
    )


def run_strict_pair(
    compiled: CompiledPair,
    tmp_path: Path,
    *,
    validate_stdout: OutputValidator | None = None,
) -> None:
    """Build and execute both outputs with every strict hosted C compiler."""
    for frontend, generated in compiled:
        for compiler in COMPILERS:
            compiler_name = Path(compiler).name
            executable = tmp_path / f"{frontend}-{compiler_name}-production"
            environment = _compiler_environment(compiler)
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
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert build.returncode == 0, build.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPO,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert run.returncode == 0, run.stderr
            if validate_stdout is not None:
                validate_stdout(run.stdout)


def run_tracked_fixture_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
) -> None:
    """Execute a dual-frontend fixture with strict allocation accounting."""
    for artifact in compile_fixture_pair(semantic_btrcc, tmp_path, fixture):
        _tracked_strict_matrix(artifact, tmp_path)


def compile_diagnostic_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    """Compile an invalid standalone source through both semantic frontends."""
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    return selfhost, reference


__all__ = [
    "compile_diagnostic_pair",
    "compile_fixture_pair",
    "run_strict_pair",
    "run_tracked_fixture_pair",
]
