"""Compile one C-compatibility program through each compiler for comparison.

test_c_compatibility_bodies.py and test_c_compatibility_function_pointers.py
lower two spellings of the same program and compare the reference compiler's
IR or C, and btrcc's C, with the program's directory masked out.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def write_program(directory: Path, source: str) -> Path:
    """Write *source* as ``Program.btrc`` so file names never differ."""
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / "Program.btrc"
    program.write_text(source)
    return program


def reference_output(program: Path, *flags: str) -> str:
    """The reference compiler's ``--emit-ir`` dump, else its generated C."""
    output = program.with_suffix(".c")
    command = [sys.executable, "-m", "src.compiler.python.main", str(program), "--no-stdlib", "--no-cache", *flags]
    if "--emit-ir" not in flags:
        command.extend(["-o", str(output)])
    result = subprocess.run(
        command,
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(program.parent / "cache")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout if "--emit-ir" in flags else output.read_text()


def selfhost_output(compiler: Path, program: Path, *flags: str) -> str:
    result = subprocess.run(
        [str(compiler), "--no-stdlib", *flags, str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def relative_to_program(text: str, program: Path) -> str:
    return text.replace(str(program.parent), "<dir>")
