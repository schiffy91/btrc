"""Code-generation contracts for standalone lexical blocks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_arc_ownership_contracts import COMPILERS, _emit

LEXICAL_BLOCK_SOURCE = r"""
    #include <assert.h>

    class Wrapper<T> {
        public void check(T first, T second) {
            { T value = first; assert(value == first); }
            { T value = second; assert(value == second); }
        }
    }

    void checkConcrete() {
        { int value = 1; assert(value == 1); }
        { int value = 2; assert(value == 2); }
    }

    int main() {
        checkConcrete();
        Wrapper<int> wrapper = new Wrapper<int>();
        wrapper.check(10, 20);
        return 0;
    }
"""


def test_standalone_blocks_remain_structured_ir_scopes():
    emitted = _emit(LEXICAL_BLOCK_SOURCE)

    assert "void checkConcrete(void) {\n    {" in emitted
    assert "    {\n        int value = first;" in emitted
    assert "    {\n        int value = second;" in emitted


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_sibling_lexical_declarations_compile_and_run(
    tmp_path: Path,
    c_compiler: str,
):
    source = tmp_path / f"lexical-blocks-{Path(c_compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(_emit(LEXICAL_BLOCK_SOURCE))
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(executable)], check=True, timeout=15)
