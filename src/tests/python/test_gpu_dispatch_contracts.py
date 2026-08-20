"""Strict-C and runtime contracts at GPU dispatch call sites."""

import re
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c
from src.tests.python.test_gpu_dispatch_failures import (
    COMPILERS,
    _compile_with_gpu_stubs,
)

GPU_INCLUDE = Path(__file__).resolve().parents[2] / "stdlib" / "gpu"
GPU_UNAVAILABLE_STUB = Path(__file__).resolve().parents[1] / "btrc" / "fixtures" / "gpu_unavailable_stub.c"


def _analyzer_errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<gpu-capacity>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


def _analyzed_despite_errors(source: str):
    program = Parser(Lexer(source, "<gpu-capacity>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


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
    source = (
        "@gpu\nvoid mix(int[] xs, int factor = 2, int bias = 1) { "
        "int i = gpu_id(); xs[i] = xs[i] * factor + bias; }\n"
        "int main() { int[] xs = {1, 2}; mix(bias=3, xs=xs); "
        "return (xs[0] == 5 && xs[1] == 7) ? 0 : 1; }"
    )
    generated = emit_c(source)
    assert "sizeof(xs) / sizeof(xs[0])" in generated
    assert not re.search(r"sizeof\(__btrc_call_operand_\d+\)", generated)
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )

    subprocess.run([str(executable)], check=True)


def test_unsized_pointer_gpu_input_is_rejected() -> None:
    errors = _analyzer_errors(
        "@gpu\nvoid update(int[] xs) { int i = gpu_id(); xs[i] += 1; }\n"
        "void run(int[] xs) { update(xs); } int main() { return 0; }"
    )
    assert any("no provable readable GPU buffer capacity" in error for error in errors)


@pytest.mark.parametrize("qualifier", ["const", "volatile"])
def test_qualified_gpu_array_parameters_are_rejected(qualifier: str) -> None:
    errors = _analyzer_errors(
        f"@gpu void inspect({qualifier} int[] xs) {{ int i = gpu_id(); int value = xs[i]; }} int main() {{ return 0; }}"
    )

    assert any("GPU array buffers are read-write" in error for error in errors)


def test_fixed_bound_parameter_output_is_rejected_by_semantics_and_codegen() -> None:
    analyzed = _analyzed_despite_errors(
        "@gpu int[] copy(int[] xs) { int i = gpu_id(); return xs[i]; } "
        "void fill(int out[2]) { int[] xs = {1, 2}; out = copy(xs); } "
        "int main() { return 0; }"
    )
    assert any("no provable writable capacity" in error for error in analyzed.errors)
    with pytest.raises(CodegenError, match="no provable writable capacity"):
        IRLowerer(analyzed).lower()


def test_incomplete_extern_output_is_rejected_by_semantics_and_codegen() -> None:
    analyzed = _analyzed_despite_errors(
        "extern int out[]; "
        "@gpu int[] copy(int[] xs) { int i = gpu_id(); return xs[i]; } "
        "int main() { int[] xs = {1}; out = copy(xs); return 0; }"
    )
    assert any("no provable writable capacity" in error for error in analyzed.errors)
    with pytest.raises(CodegenError, match="no provable writable capacity"):
        IRLowerer(analyzed).lower()


def test_global_array_alias_input_is_rejected_by_semantics_and_codegen() -> None:
    analyzed = _analyzed_despite_errors(
        "typedef int[] Values; int backing[2] = {1, 2}; "
        "Values view = backing; "
        "@gpu void bump(int[] xs) { int i = gpu_id(); xs[i] += 1; } "
        "int main() { bump(view); return 0; }"
    )
    assert any("no provable readable GPU buffer capacity" in error for error in analyzed.errors)
    with pytest.raises(CodegenError, match="has no provable capacity"):
        IRLowerer(analyzed).lower()


def test_unknown_capacity_gpu_array_default_is_rejected_semantically() -> None:
    errors = _analyzer_errors(
        "extern int defaults[]; "
        "@gpu int[] copy(int[] values = defaults) { "
        "int i = gpu_id(); return values[i]; } "
        "int main() { int[] output = copy(); return output[0]; }"
    )
    assert any(
        "Default for parameter 'values' has no provable readable GPU buffer capacity" in error for error in errors
    )


def test_hosted_macro_named_real_array_is_rejected_before_capacity_lowering() -> None:
    source = (
        "@gpu\nvoid update(int[] values) { int i = gpu_id(); values[i] += 1; }\n"
        "int main() { int[] stdin = {1}; update(stdin); return 0; }"
    )
    program = Parser(Lexer(source, "<gpu-capacity>").tokenize()).parse()
    errors = SemanticAnalyzer().analyze(program).errors
    assert any("stdin" in error and "automatically included C macro" in error for error in errors)


@pytest.mark.parametrize(
    "source",
    [
        (
            "@gpu\nvoid update(int[] xs) { int i = gpu_id(); xs[i] += 1; }\n"
            "void run() { int[] xs = {1}; { int[] xs; update(xs); } } "
            "int main() { return 0; }"
        ),
        (
            "int[] xs = {1}; "
            "@gpu\nvoid update(int[] values) { int i = gpu_id(); values[i] += 1; }\n"
            "void run(int[] xs) { update(xs); } int main() { return 0; }"
        ),
    ],
)
def test_pointer_shadow_does_not_borrow_outer_gpu_array_extent(source: str) -> None:
    errors = _analyzer_errors(source)
    assert any(
        "array bound or initializer" in error or "no provable readable GPU buffer capacity" in error for error in errors
    )


def test_pointer_output_shadow_does_not_borrow_outer_array_capacity() -> None:
    errors = _analyzer_errors(
        "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
        "void run() { int[] out = {0}; { int[] out; int[] xs = {1}; "
        "out = copy(xs); } } int main() { return 0; }"
    )
    assert any("array bound or initializer" in error for error in errors)


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
    size = re.search(
        r"int (__gpu_len_\d+);.*?\(\1 = __gpu_arg_\d+->len\)",
        c_source,
        re.DOTALL,
    )
    assert size is not None
    name = re.escape(size.group(1))
    assert re.search(
        rf"int out\[\(\({name} > 0\) \? {name} : 1\)\];",
        c_source,
    )
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
    errors = _analyzer_errors(
        "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
        "void fill(int[] out) { int[] xs = {1}; out = copy(xs); }\n"
        "int main() { return 0; }"
    )
    assert any("no provable writable capacity" in error for error in errors)


def test_departed_array_shadow_does_not_lend_capacity_to_parameter() -> None:
    errors = _analyzer_errors(
        "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
        "void fill(int[] out) { { int[] out = {0}; } int[] xs = {1}; "
        "out = copy(xs); }\n"
        "int main() { return 0; }"
    )
    assert any("no provable writable capacity" in error for error in errors)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_live_gpu_dispatch_materializes_runtime_header_strictly(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    c_source = emit_c(
        "@gpu void bump(int[] xs) { int i = gpu_id(); xs[i] += 1; } "
        "int main() { int xs[1] = {1}; bump(xs); return xs[0] == 2 ? 0 : 1; }"
    )
    assert c_source.count("#include <btrc_gpu.h>") == 1
    unit = tmp_path / "live_gpu.c"
    binary = tmp_path / "live_gpu"
    unit.write_text(c_source)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{GPU_INCLUDE}",
            str(unit),
            str(GPU_UNAVAILABLE_STUB),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_dead_gpu_kernel_leaves_no_unused_shader_constant(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    c_source = emit_c("@gpu\nvoid dormant(int[] xs) { int i = gpu_id(); xs[i] += 1; }\nint main() { return 0; }")
    assert "dormant_wgsl" not in c_source
    assert "dormant__gpucpu" not in c_source
    assert "#include <btrc_gpu.h>" not in c_source
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
