"""Strict-C11 runtime coverage for generic type and symbol identities."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

RUNTIME_SOURCE = """
#include <assert.h>

typedef int A_int;
typedef int A_int_p1;
typedef __fn_ptr<int, int> Unary;

int increment(int value) { return value + 1; }

class A<T> { public A() {} }
class Holder<T> {
    public Holder() {}
    public int marker() { return 1; }
}
class Holder_A<T> {
    public Holder_A() {}
    public int marker() { return 2; }
}
class Picker {
    public U identity<U>(U value) { return value; }
}
class Callbacks {
    public Unary instance;
    public Unary property { get; set; }
    class Unary shared = increment;
    public Callbacks(Unary callback) {
        self.instance = callback;
        self.property = callback;
    }
}

int main() {
    Holder<int> scalar = new Holder<int>();
    Holder<int[]> array = new Holder<int[]>();
    Holder<int?> nullable = new Holder<int?>();
    Holder<int*> pointer = new Holder<int*>();
    Holder<A<int>> nested = new Holder<A<int>>();
    Holder<A_int_p1> flat = new Holder<A_int_p1>();
    Holder_A<int> unsafeOuter = new Holder_A<int>();
    Holder<A_int> unsafeArgument = new Holder<A_int>();

    int markers = scalar.marker() + array.marker() + nullable.marker()
        + pointer.marker() + nested.marker() + flat.marker()
        + unsafeOuter.marker() + unsafeArgument.marker();
    assert(markers == 9);

    Picker picker = Picker();
    A<int> object = new A<int>();
    A<int> objectCopy = picker.identity(object);
    A_int_p1 number = 7;
    A_int_p1 numberCopy = picker.identity(number);
    int values[2] = {4, 9};
    int* valuesCopy = picker.identity(values);
    int scalarCopy = picker.identity(5);
    assert(objectCopy == object);
    assert((int)numberCopy == 7);
    assert(valuesCopy[1] == 9);
    assert(scalarCopy == 5);

    Unary local = increment;
    Callbacks callbacks = Callbacks(local);
    assert(local(8) == 9);
    assert(callbacks.instance(9) == 10);
    assert(callbacks.property(10) == 11);
    assert(Callbacks.shared(11) == 12);
    return 0;
}
"""


@pytest.mark.skipif(
    not COMPILERS or sys.platform == "win32",
    reason="requires a hosted C11 compiler",
)
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_class_and_method_type_identities_compile_and_run_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    source = tmp_path / "type_identity.c"
    binary = tmp_path / "type_identity"
    source.write_text(emit_c(RUNTIME_SOURCE))

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            str(source),
            "-lm",
            "-pthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([binary], check=True, capture_output=True, text=True)
