"""The self-hosted compiler loads the generated stdlib symbol index and falls back when it is stale."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STDLIB = REPO / "src/stdlib"
PROGRAM = "int main() { Vector<int> values = [1, 2]; return values.len == 2 ? 0 : 1; }\n"


def _stdlib_copy(home: Path) -> Path:
    """A BTRC_HOME holding the grammar and a private copy of the stdlib."""
    shutil.copytree(REPO / "src/language", home / "language")
    root = home / "stdlib"
    shutil.copytree(STDLIB, root)
    return root


def _visibility_failure(btrcc: Path, home: Path, tmp_path: Path) -> str:
    source = tmp_path / "Main.btrc"
    source.write_text(PROGRAM, encoding="utf-8")
    result = subprocess.run(
        [str(btrcc), "--strict-imports", str(source)],
        cwd=REPO,
        env={**os.environ, "BTRC_HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stderr if result.returncode != 0 else ""


def test_selfhost_consults_the_index_when_current_and_parses_when_stale(immutable_btrcc: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = _stdlib_copy(home)
    index = root / "btrc.symbols"
    lines = index.read_text(encoding="utf-8").split("\n")
    assert lines[0].startswith("btrc-symbols 1 ")
    assert any(line.startswith("Vector\t") for line in lines)

    # Strict imports reject an unimported stdlib symbol the index attributes to Vector.btrc.
    pristine = _visibility_failure(immutable_btrcc, home, tmp_path)
    assert "Vector" in pristine and "Vector.btrc" in pristine

    # Dropping that attribution from a current index changes the verdict: the index was consulted.
    index.write_text("\n".join(line for line in lines if not line.startswith("Vector\t")), encoding="utf-8")
    assert _visibility_failure(immutable_btrcc, home, tmp_path) == ""

    # A stale digest is ignored: the compiler parses the modules and finds the owner again.
    stale = lines[0].replace(lines[0].split(" ")[2][:8], "00000000")
    index.write_text(
        "\n".join([stale, *[line for line in lines[1:] if not line.startswith("Vector\t")]]), encoding="utf-8"
    )
    assert _visibility_failure(immutable_btrcc, home, tmp_path) == pristine

    # So is a missing index, and the compiler never writes one.
    index.unlink()
    assert _visibility_failure(immutable_btrcc, home, tmp_path) == pristine
    assert not index.exists()
