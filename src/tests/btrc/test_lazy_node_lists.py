"""The generated AST node's lazy list storage, and the guard on its shared empty.

A lazy list field reads as one shared empty until it is written. Mutating what
a reader answered would fill that empty for every unwritten field in the
program, so each reader checks it is still empty and stops the compiler if not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DRIVER = REPO / "src/tests/btrc/fixtures/LazyNodeListDriver.btrc"


def _run(binary: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(binary), *arguments], capture_output=True, text=True, timeout=60)


def test_unwritten_lists_read_empty_and_writes_stay_on_their_node(selfhost_driver) -> None:
    result = _run(selfhost_driver(DRIVER))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok\n"


def test_mutating_a_list_answered_by_a_reader_stops_the_compiler(selfhost_driver) -> None:
    result = _run(selfhost_driver(DRIVER), "misuse")
    assert result.returncode == 1
    assert "unreachable" not in result.stdout
    assert "Node.sharedEmptyNodes is no longer empty" in result.stderr
