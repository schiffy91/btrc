"""Frontend parity: brace initializers with elements never name a managed collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "import Library.Set;\nint main() { Set<int> seen = {1, 2, 3}; return seen.size(); }",
            "cannot use a non-empty brace initializer for 'Set'; '{}' creates an empty Set and add() inserts elements",
        ),
        (
            "import Library.Vector;\nint main() { Vector<int> xs = {1, 2}; return xs.size(); }",
            "cannot use a non-empty brace initializer for 'Vector'",
        ),
    ],
)
def test_collection_brace_initializers_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_empty_brace_collections_still_compile_on_both_frontends(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = "import Library.Set;\nint main() { Set<int> seen = {}; seen.add(1); return seen.size() == 1 ? 0 : 1; }"
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
