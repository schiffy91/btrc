"""Runtime ownership parity for managed values stored by literals."""

from __future__ import annotations

from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    compile_reference_source,
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import (
    REPO,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = REPO / "src/tests/btrc/fixtures/collection_literal_ownership_runtime.btrc"


def _compile_both(semantic_btrcc: Path, tmp_path: Path):
    source = FIXTURE.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source, no_stdlib=False)
    reference, reference_source = compile_reference_source(tmp_path, source, "collection-literals")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def test_collection_literals_consume_fresh_managed_values(semantic_btrcc: Path, tmp_path: Path) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-collection-literals")
    _strict_build_and_run(reference_source, tmp_path / "reference-collection-literals")


def test_collection_literal_ownership_is_sanitizer_clean(semantic_btrcc: Path, tmp_path: Path) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    sanitized_build_and_run(selfhost_source, tmp_path / "selfhost-collection-literals-san")
    sanitized_build_and_run(reference_source, tmp_path / "reference-collection-literals-san")
