"""btrcc command-line shape: options may surround the single input file."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PROGRAM = REPO / "src/tests/basics/BoolToString.btrc"


def _run(compiler: Path, *arguments: str):
    return subprocess.run([str(compiler), *arguments], cwd=REPO, capture_output=True, text=True, timeout=300)


def test_output_and_debug_may_follow_the_input(immutable_btrcc, tmp_path):
    out = tmp_path / "program.c"
    result = _run(immutable_btrcc, "--strict-imports", str(PROGRAM), "-o", str(out), "--debug")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert f'"{PROGRAM}"' in out.read_text()


def test_options_before_the_input_still_work(immutable_btrcc, tmp_path):
    out = tmp_path / "program.c"
    result = _run(immutable_btrcc, "-o", str(out), "--strict-imports", "--", str(PROGRAM))
    assert result.returncode == 0, result.stderr
    assert "#line" not in out.read_text()


def test_two_inputs_are_rejected(immutable_btrcc):
    result = _run(immutable_btrcc, str(PROGRAM), str(PROGRAM))
    assert result.returncode != 0
    assert "only one input file" in result.stderr


def test_output_needs_a_path(immutable_btrcc):
    result = _run(immutable_btrcc, str(PROGRAM), "-o")
    assert result.returncode != 0
    assert "-o requires an output path" in result.stderr
