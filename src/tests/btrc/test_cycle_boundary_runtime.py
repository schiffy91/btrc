"""Strict dual-compiler coverage for edge-only cycle boundaries."""

from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix

FIXTURE = Path(__file__).with_name("fixtures") / "CycleEdgeBoundaryRuntime.btrc"


@pytest.mark.parametrize("generic_method", [False, True], ids=["ordinary-method", "generic-method"])
@pytest.mark.parametrize("return_early", [False, True], ids=["fallthrough", "early-return"])
def test_edge_only_collection_boundary_forces_subthreshold_cycle(
    semantic_btrcc: Path,
    tmp_path: Path,
    return_early: bool,
    generic_method: bool,
) -> None:
    source = FIXTURE.read_text().replace("roots.clear(false)", f"roots.clear({str(return_early).lower()})")
    if generic_method:
        source = source.replace("clear(bool returnEarly)", "clear<U>(U returnEarly)")
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        source,
        FIXTURE.stem,
    )

    for artifact in compiled:
        strict_c11_matrix(artifact, tmp_path)
