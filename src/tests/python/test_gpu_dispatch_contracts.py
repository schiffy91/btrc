"""Strict-C and runtime contracts at GPU dispatch call sites."""

import re
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.errors import CodegenError
from src.tests.python.test_codegen import emit_c
from src.tests.python.test_gpu_dispatch_failures import (
    COMPILERS,
    _compile_with_gpu_stubs,
)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("available", [False, True], ids=["cpu", "gpu"])
def test_output_capacity_mismatch_fails_before_dispatch(
    tmp_path: Path,
    c_compiler: str,
    available: bool,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu\nint[] dbl(int[] xs) { int i = gpu_id(); return xs[i] * 2; }\n"
        "int main() { int[] xs = {1, 2}; int out[1]; "
        "out = dbl(xs); return 0; }",
        available=available,
        fail_second_buffer=False,
        compiler=c_compiler,
    )

    result = subprocess.run([str(executable)], capture_output=True, text=True)

    assert result.returncode != 0
    assert "output capacity is smaller than dispatch length" in result.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_named_gpu_arguments_and_defaults_follow_parameter_order(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu\nvoid mix(int[] xs, int factor = 2, int bias = 1) { "
        "int i = gpu_id(); xs[i] = xs[i] * factor + bias; }\n"
        "int main() { int[] xs = {1, 2}; mix(bias=3, xs=xs); "
        "return (xs[0] == 5 && xs[1] == 7) ? 0 : 1; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )

    subprocess.run([str(executable)], check=True)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_zero_length_collection_result_uses_nonzero_c_storage(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = (
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } }\n"
        "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
        "int main() { int raw[1] = {7}; Vector<int> empty = "
        "new Vector<int>(raw, 0); int[] out = copy(empty); return 0; }"
    )
    c_source = emit_c(source)
    assert re.search(r"int out\[\(\([^]]+->len > 0\) \? [^]]+->len : 1\)\];", c_source)
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )

    subprocess.run([str(executable)], check=True)


def test_explicit_gpu_output_bound_is_evaluated_once() -> None:
    c_source = emit_c(
        "int calls = 0; int size() { calls++; return 2; }\n"
        "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
        "int main() { int[] xs = {1, 2}; int out[size()] = copy(xs); "
        "return calls; }"
    )

    assert c_source.count("= size();") == 1
    assert "__gpu_output_size" in c_source


def test_unsized_pointer_output_target_is_rejected() -> None:
    with pytest.raises(CodegenError, match="no provable writable capacity"):
        emit_c(
            "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
            "void fill(int[] out, int[] xs) { out = copy(xs); }\n"
            "int main() { return 0; }"
        )


def test_departed_array_shadow_does_not_lend_capacity_to_parameter() -> None:
    with pytest.raises(CodegenError, match="no provable writable capacity"):
        emit_c(
            "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
            "void fill(int[] out, int[] xs) { { int[] out = {0}; } "
            "out = copy(xs); }\n"
            "int main() { return 0; }"
        )


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_dead_gpu_kernel_leaves_no_unused_shader_constant(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    c_source = emit_c("@gpu\nvoid dormant(int[] xs) { int i = gpu_id(); xs[i] += 1; }\nint main() { return 0; }")
    assert "dormant_wgsl" not in c_source
    assert "dormant__gpucpu" not in c_source
    unit = tmp_path / "dead_gpu.c"
    unit.write_text(c_source)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            str(unit),
            "-o",
            str(tmp_path / "dead_gpu"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_bool_uniform_layout_compiles_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = (
        "@gpu\nvoid choose(float threshold, bool enabled, int bias, int[] xs) { "
        "int i = gpu_id(); if (enabled) { xs[i] = (int)threshold + bias; } }\n"
        "int main() { int[] xs = {0}; choose(2.0, true, 3, xs); "
        "return xs[0] == 5 ? 0 : 1; }"
    )
    c_source = emit_c(source)
    assert "uint32_t enabled;" in c_source
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )

    subprocess.run([str(executable)], check=True)
