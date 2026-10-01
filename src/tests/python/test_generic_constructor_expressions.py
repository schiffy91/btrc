"""Runtime coverage for generic constructors in expression positions."""

import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import HOST_C_COMPILERS
from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.test_codegen import emit_c

RUNTIME_SOURCE = """
#include <assert.h>

class Box<T> {
    public T value;
    public Box(T value) { self.value = value; }
}

class Empty<T> {}

int takeBox(Box<int> box) {
    return box.value;
}

Box<int> makeBox(int value) {
    return Box(value);
}

int nestedValue() {
    return Box(Box(9)).value.value;
}

int takeEmpty(Empty<int> value) {
    return value != null ? 1 : 0;
}

Empty<int> makeEmpty() {
    return Empty();
}

Box<Empty<int>> makeNestedEmpty() {
    return Box(Empty());
}

int main() {
    assert(takeBox(Box(7)) == 7);
    assert(makeBox(8).value == 8);
    assert(nestedValue() == 9);
    assert(takeEmpty(Empty()) == 1);
    assert(makeEmpty() != null);
    assert(makeNestedEmpty().value != null);
    return 0;
}
"""


@pytest.mark.skipif(
    not HOST_C_COMPILERS or sys.platform == "win32",
    reason="requires a hosted C11 compiler",
)
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_generic_constructors_compile_and_run_in_all_expression_positions(
    tmp_path: Path,
    c_compiler: str,
):
    source = tmp_path / "generic_constructor_expressions.c"
    executable = source.with_suffix("")
    source.write_text(emit_c(RUNTIME_SOURCE))

    subprocess.run(
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
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
