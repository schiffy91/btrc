"""Frozen runtime contracts for terminal ARC lifecycle state and draining."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_mutex_value_contract import (
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
RUNTIME_CASES = (
    "lifecycle_throwing_owner_runtime.btrc",
    "lifecycle_throwing_cycle_runtime.btrc",
    "lifecycle_fifo_errors_runtime.btrc",
    "lifecycle_empty_error_runtime.btrc",
    "lifecycle_constructor_abandon_runtime.btrc",
    "lifecycle_shared_delete_runtime.btrc",
    "lifecycle_resurrection_runtime.btrc",
)
SANITIZER_CASES = (
    "lifecycle_throwing_owner_runtime.btrc",
    "lifecycle_throwing_cycle_runtime.btrc",
    "lifecycle_empty_error_runtime.btrc",
    "lifecycle_constructor_abandon_runtime.btrc",
    "lifecycle_resurrection_runtime.btrc",
)


def _compile_case(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> tuple[tuple[str, Path], ...]:
    fixture = FIXTURES / fixture_name
    return _compile_pair(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
        fixture.stem,
    )


@pytest.mark.parametrize("fixture_name", RUNTIME_CASES)
def test_arc_lifecycle_state_has_strict_dual_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    for artifact in _compile_case(semantic_btrcc, tmp_path, fixture_name):
        _strict_matrix(artifact, tmp_path)


@pytest.mark.parametrize("fixture_name", SANITIZER_CASES)
def test_arc_lifecycle_teardown_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    toolchain = require_sanitizers(tmp_path)
    for compiler_name, generated in _compile_case(
        semantic_btrcc,
        tmp_path,
        fixture_name,
    ):
        sanitized_build_and_run(
            generated,
            tmp_path / f"{compiler_name}-{Path(fixture_name).stem}-san",
            toolchain,
        )
