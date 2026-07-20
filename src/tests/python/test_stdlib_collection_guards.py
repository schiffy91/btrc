"""Runtime coverage for collection allocation and capacity guards."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("setup", "operation", "diagnostic"),
    [
        (
            "Vector<int> value = []; value.cap = 1073741824; value.len = value.cap;",
            "value.push(1);",
            "Vector capacity overflow",
        ),
        (
            "List<int> value = new List<int>(); value.len = 2147483647;",
            "value.push(1);",
            "List length overflow",
        ),
        (
            "",
            "Array<int> value = new Array<int>(-1);",
            "Array size must be non-negative",
        ),
        (
            "Map<int, int> value = {}; value.cap = 1073741824; value.len = 805306368;",
            "value.put(1, 1);",
            "Map capacity overflow",
        ),
        (
            "Set<int> value = {}; value.cap = 1073741824; value.len = 805306368;",
            "value.add(1);",
            "Set capacity overflow",
        ),
    ],
)
def test_collection_growth_fails_before_integer_overflow(tmp_path, setup, operation, diagnostic):
    source = tmp_path / "guard.btrc"
    c_source = tmp_path / "guard.c"
    executable = tmp_path / "guard"
    source.write_text(f"int main() {{\n    {setup}\n    {operation}\n    return 0;\n}}\n")

    transpile = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-cache",
            "-o",
            str(c_source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert transpile.returncode == 0, transpile.stderr

    compile_result = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-pedantic-errors",
            str(c_source),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    run = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    assert diagnostic in run.stderr
