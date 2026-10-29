"""The native jump owner uses the same scope and reachability contracts."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import strict_build_and_run

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name("fixtures") / "JumpScopeIndexDriver.btrc"


@pytest.fixture(scope="module")
def reference_jump_index_c(tmp_path_factory):
    directory = tmp_path_factory.mktemp("jump-index")
    generated = directory / "index.c"
    result = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(SOURCE), "--no-cache", "-o", str(generated)],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return generated


def test_native_index_transpiles(reference_jump_index_c):
    assert reference_jump_index_c.is_file()


def test_native_index_contract(reference_jump_index_c, tmp_path):
    strict_build_and_run(reference_jump_index_c, tmp_path / "jump-index", optimization="-O0")
