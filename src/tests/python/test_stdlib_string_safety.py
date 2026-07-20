"""Strict runtime coverage for null-safe stdlib string composition."""

from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.frontend import compile_frontend
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

STRING_SOURCE = r"""
import std.console;
import std.strings;
import std.vector;
#include <assert.h>
#include <string.h>

int main() {
    string? missing = null;
    Vector<string> values = ["a"];
    values.push(missing);
    values.push("c");
    string joined = values.join(null);
    assert(strcmp(joined, "ac") == 0);

    Vector<string> nulls = [];
    nulls.push(missing);
    nulls.push(missing);
    string separated = nulls.join(",");
    assert(strcmp(separated, ",") == 0);

    assert(Strings.checkedLength(missing) == 0);
    string repeated = "ignored".repeat(0);
    assert(strcmp(repeated, "") == 0);
    Console.writeLine(missing);
    return 0;
}
"""


@functools.lru_cache(maxsize=1)
def _emit_string_runtime() -> str:
    analyzed = compile_frontend(
        STRING_SOURCE,
        __file__,
        filename="<stdlib-string-safety>",
    ).analyzed
    assert not analyzed.errors
    return CEmitter().emit(optimize(IRGenerator(analyzed).generate()))


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_nullable_vector_join_and_console_are_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    c_path = tmp_path / "stdlib_string_safety.c"
    binary = tmp_path / "stdlib_string_safety"
    c_path.write_text(_emit_string_runtime())
    compiled = subprocess.run(
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
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run(
        [str(binary)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
