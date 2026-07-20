"""Strict dual-compiler coverage for edge-only cycle boundaries."""

from pathlib import Path

from src.tests.btrc.test_mutex_value_contract import (
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "cycle_edge_boundary_runtime.btrc"


def test_edge_only_collection_boundary_forces_subthreshold_cycle(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURE.read_text(),
        FIXTURE.stem,
    )

    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)
