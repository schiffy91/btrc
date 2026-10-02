"""Build generated C as strict C11 with one host compiler and run it."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT


def compile_and_run(c_source: str, tmp_path: Path, compiler: str):
    source_path = tmp_path / "program.c"
    binary_path = tmp_path / "program"
    source_path.write_text(c_source)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source_path),
            "-o",
            str(binary_path),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    return ran
