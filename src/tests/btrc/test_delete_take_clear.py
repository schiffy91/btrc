"""Terminal-delete ownership transfer and topology contracts."""

from __future__ import annotations

from pathlib import Path

from src.tests.btrc.test_mutex_value_contract import (
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "delete_take_clear_runtime.btrc"


def test_delete_takes_and_clears_before_throwing_destructor(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURE.read_text(),
        "delete-take-clear",
    )
    for artifact in compiled:
        generated = artifact[1].read_text()
        main = generated[generated.rindex("int main(") :]
        assert main.count("selectedIndex()") == 1
        owner = main.index("selectedIndex()")
        destroy = main.index("__btrc_arc_destroy_edge(", owner)
        assert owner < destroy
        assert "__btrc_arc_slot_access_" in main[destroy : destroy + 300]
        assert "__btrc_arc_destroy(" not in generated
        _strict_matrix(artifact, tmp_path)
