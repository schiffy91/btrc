"""The runtime's platform and architecture probes on every target row.

`__btrc_target_platform()` and `__btrc_target_architecture()` are fixed when
the C compiler compiles them, so each row's code is read from clang's
optimized IR for that row's triple: no SDK, sysroot or device is needed. iOS
must not report macOS, nor Android Linux (CL-P1-16).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS

REPO = Path(__file__).resolve().parents[3]
CORE = REPO / "src/runtime/c/core.c"
PLATFORM_CODES = {"macos": 1, "linux": 2, "windows": 3, "ios": 4, "android": 5}
ARCHITECTURE_CODES = {"x86_64": 1, "aarch64": 2}


def _helper(name: str) -> str:
    text = CORE.read_text(encoding="utf-8")
    match = re.search(
        rf"/\* btrc-runtime-helper:begin {name} \*/\n(.*?)/\* btrc-runtime-helper:end {name} \*/", text, re.DOTALL
    )
    assert match is not None, name
    return match.group(1)


def _returned(row, function: str, tmp_path: Path) -> int:
    source = tmp_path / f"{row.label}-{function}.c"
    source.write_text(_helper(function) + f"int probe(void) {{ return {function}(); }}\n", encoding="utf-8")
    compiled = subprocess.run(
        [
            "clang",
            "-cc1",
            "-triple",
            row.triple,
            "-std=c11",
            "-O1",
            "-emit-llvm",
            "-o",
            "-",
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    match = re.search(r"define\b[^\n]*@probe\(\)[^\n]*\{\n(?:[^\n]*\n)*?\s*ret i32 (\d+)", compiled.stdout)
    assert match is not None, compiled.stdout
    return int(match.group(1))


@pytest.mark.skipif(shutil.which("clang") is None, reason="needs clang for per-triple IR")
@pytest.mark.parametrize("row", TARGET_ROWS, ids=[row.label for row in TARGET_ROWS])
def test_runtime_probes_report_each_rows_platform_and_architecture(row, tmp_path: Path) -> None:
    assert _returned(row, "__btrc_target_platform", tmp_path) == PLATFORM_CODES[row.operating_system]
    assert _returned(row, "__btrc_target_architecture", tmp_path) == ARCHITECTURE_CODES[row.architecture]
