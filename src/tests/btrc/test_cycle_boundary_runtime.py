"""Strict dual-compiler coverage for edge-only cycle boundaries."""

from pathlib import Path

from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix

FIXTURE = Path(__file__).with_name("fixtures") / "CycleEdgeBoundaryRuntime.btrc"


def test_edge_only_collection_boundary_forces_subthreshold_cycle(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURE.read_text(),
        FIXTURE.stem,
    )

    for artifact in compiled:
        strict_c11_matrix(artifact, tmp_path)
