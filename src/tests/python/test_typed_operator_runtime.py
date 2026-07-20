"""Strict compiler execution for the shared typed-operator runtime."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c
from src.tests.python.test_typed_operator_contract import (
    COMPILERS,
    RUNTIME_SOURCE,
)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_typed_operator_runtime_is_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    c_path = tmp_path / "typed_operators.c"
    binary = tmp_path / "typed_operators"
    c_path.write_text(emit_c(RUNTIME_SOURCE))
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
