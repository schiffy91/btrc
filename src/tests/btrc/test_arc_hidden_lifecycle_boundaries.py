"""Hidden Thread/Mutex boundaries must force sub-threshold ARC collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.allocation_tracking_harness import FIXTURES, tracked_strict_matrix
from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix

BOUNDARY_CASES = (
    "ThreadUnjoinedCycleBoundaryRuntime.btrc",
    "MutexCycleBoundaryRuntime.btrc",
)
THROWING_BOUNDARY_CASES = (
    "ThreadThrowingCycleBoundaryRuntime.btrc",
    "MutexThrowingCycleBoundaryRuntime.btrc",
)
WORKER_TEARDOWN_CASE = "ThreadWorkerTeardownOrderRuntime.btrc"
WORKER_CLEANUP_ERROR_CASE = "ThreadWorkerCleanupErrorRuntime.btrc"
WORKER_ENTRY_ERROR_CASE = "ThreadWorkerEntryErrorRuntime.btrc"
MUTEX_SET_BOUNDARY_CASE = "MutexSetCycleBoundaryRuntime.btrc"
MUTEX_RETAIN_FAILURE_CASE = "MutexRetainFailureRuntime.btrc"
EMPTY_CALLBACK_ERROR_CASE = "ThreadMutexEmptyErrorRuntime.btrc"
MUTEX_FIELD_CLEANUP_CASE = "MutexFieldCleanupRuntime.btrc"


@pytest.mark.parametrize("fixture_name", BOUNDARY_CASES)
def test_hidden_arc_boundaries_force_subthreshold_cycles(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    fixture = FIXTURES / fixture_name
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        strict_c11_matrix(artifact, tmp_path)


@pytest.mark.parametrize("fixture_name", THROWING_BOUNDARY_CASES)
def test_hidden_arc_boundaries_free_wrappers_before_rethrow(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    fixture = FIXTURES / fixture_name
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)


def test_worker_arc_cleanup_precedes_final_try_state_cleanup(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / WORKER_TEARDOWN_CASE
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)


def test_worker_arc_cleanup_error_transfers_after_reclaiming_results(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / WORKER_CLEANUP_ERROR_CASE
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)


def test_worker_entry_and_capture_errors_transfer_after_full_cleanup(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / WORKER_ENTRY_ERROR_CASE
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)


def test_mutex_set_forces_old_cycle_and_preserves_callback_error(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / MUTEX_SET_BOUNDARY_CASE
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)


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
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)
