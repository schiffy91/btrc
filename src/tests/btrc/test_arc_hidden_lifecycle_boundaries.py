"""Hidden Thread/Mutex boundaries must force sub-threshold ARC collection."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    REPO,
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
BOUNDARY_CASES = (
    "thread_unjoined_cycle_boundary_runtime.btrc",
    "mutex_cycle_boundary_runtime.btrc",
)
THROWING_BOUNDARY_CASES = (
    "thread_throwing_cycle_boundary_runtime.btrc",
    "mutex_throwing_cycle_boundary_runtime.btrc",
)
WORKER_TEARDOWN_CASE = "thread_worker_teardown_order_runtime.btrc"
WORKER_CLEANUP_ERROR_CASE = "thread_worker_cleanup_error_runtime.btrc"
WORKER_ENTRY_ERROR_CASE = "thread_worker_entry_error_runtime.btrc"
MUTEX_SET_BOUNDARY_CASE = "mutex_set_cycle_boundary_runtime.btrc"
MUTEX_RETAIN_FAILURE_CASE = "mutex_retain_failure_runtime.btrc"
EMPTY_CALLBACK_ERROR_CASE = "thread_mutex_empty_error_runtime.btrc"
MUTEX_FIELD_CLEANUP_CASE = "mutex_field_cleanup_runtime.btrc"
ALLOCATION_TRACKER = FIXTURES / "arc_boundary_alloc_tracker.c"
ALLOCATION_REDIRECTS = (
    "-Dmalloc=btrc_test_malloc",
    "-Dcalloc=btrc_test_calloc",
    "-Drealloc=btrc_test_realloc",
    "-Dfree=btrc_test_free",
)


def _compiler_environment(compiler: str) -> dict[str, str] | None:
    if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
        return None
    environment = {
        name: os.environ[name]
        for name in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        if name in os.environ
    }
    environment.update({"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": "/tmp"})
    return environment


def _tracked_strict_matrix(compiled: tuple[str, Path], tmp_path: Path) -> None:
    for compiler in COMPILERS:
        output = tmp_path / f"{compiled[0]}-{Path(compiler).name}-tracked"
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
                *ALLOCATION_REDIRECTS,
                str(compiled[1]),
                str(ALLOCATION_TRACKER),
                "-pthread",
                "-lm",
                "-o",
                str(output),
            ],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run(
            [str(output)],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("fixture_name", BOUNDARY_CASES)
def test_hidden_arc_boundaries_force_subthreshold_cycles(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    fixture = FIXTURES / fixture_name
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


@pytest.mark.parametrize("fixture_name", THROWING_BOUNDARY_CASES)
def test_hidden_arc_boundaries_free_wrappers_before_rethrow(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    fixture = FIXTURES / fixture_name
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)


def test_worker_arc_cleanup_precedes_final_try_state_cleanup(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / WORKER_TEARDOWN_CASE
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)


def test_worker_arc_cleanup_error_transfers_after_reclaiming_results(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / WORKER_CLEANUP_ERROR_CASE
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)


def test_worker_entry_and_capture_errors_transfer_after_full_cleanup(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / WORKER_ENTRY_ERROR_CASE
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)


def test_mutex_set_forces_old_cycle_and_preserves_callback_error(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / MUTEX_SET_BOUNDARY_CASE
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)


@pytest.mark.parametrize(
    "fixture_name",
    (
        MUTEX_RETAIN_FAILURE_CASE,
        EMPTY_CALLBACK_ERROR_CASE,
        MUTEX_FIELD_CLEANUP_CASE,
    ),
)
def test_guarded_thread_mutex_failures_release_all_resources(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    fixture = FIXTURES / fixture_name
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        _tracked_strict_matrix(artifact, tmp_path)
