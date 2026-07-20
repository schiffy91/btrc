"""Strict source-order contracts for lowered string helper calls."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compile_and_run(tmp_path: Path, compiler: str, generated: str):
    source = tmp_path / "string_method_ordering.c"
    binary = tmp_path / "string_method_ordering"
    source.write_text(generated)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run(
        [str(binary)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


ORDERING_BODY = """
    int index = 0;
    string part = text.substring((index = 1), index + 1);
    if (strcmp(part, "bc") != 0) { return 2; }

    string needle = "x";
    string replaced = text.replace((needle = "b"), needle);
    if (strcmp(replaced, "abcd") != 0) { return 3; }

    string receiver = "old";
    int offset = 0;
    string selected = (receiver = "wxyz").substring(
        (offset = 1), offset + 1);
    if (strcmp(selected, "xy") != 0) { return 4; }
    return 0;
"""


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_primary_string_helpers_sequence_receiver_and_arguments(tmp_path, c_compiler):
    generated = emit_c('int main() { string text = "abcd";' + ORDERING_BODY + "}")

    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_generic_string_helpers_use_the_same_ordering_boundary(tmp_path, c_compiler):
    generated = emit_c(
        "class Ops<T> { public Ops() {} public int verify(string text) {"
        + ORDERING_BODY
        + "} } int main() { Ops<int> ops = new Ops<int>(); "
        + 'return ops.verify("abcd"); }'
    )

    result = _compile_and_run(tmp_path, c_compiler, generated)
    assert result.returncode == 0, result.stderr
