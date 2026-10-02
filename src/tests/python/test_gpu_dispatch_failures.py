"""Failure-path contracts for generated @gpu compute dispatches."""

import re
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.c_toolchains import HOST_C_COMPILERS, requires_host_c_compiler
from src.tests.process_limits import RUN_TIMEOUT
from src.tests.python.gpu_stub_fixtures import compile_with_gpu_stubs
from src.tests.python.reference_pipeline import emit_c


def test_void_dispatch_guards_handles_and_records_recovery() -> None:
    c_source = emit_c(
        "@gpu\nvoid scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; }\n"
        "int main() { int[] xs = {1, 2}; scale(xs); return 0; }"
    )
    prefix = _dispatch_prefixes(c_source)[0]
    for role in ("gpu", "buf_xs", "buf_uniforms", "shader", "pipeline", "bind_group"):
        assert re.search(
            rf"if \(!{prefix}_{role}\) \{{\s+{prefix}_ok = false;",
            c_source,
        )
    assert c_source.index(f"btrc_gpu_buffer_destroy({prefix}_buf_xs)") < c_source.index(
        "scale__gpucpu(", c_source.index(f"static void {prefix}_run")
    )


def test_array_return_dispatch_has_per_invocation_cpu_fallback() -> None:
    c_source = emit_c(
        "@gpu\nint[] dbl(int[] xs) { int i = gpu_id(); return xs[i] * 2; }\n"
        "int main() { int[] xs = {1, 2}; int[] out = {0, 0}; "
        "out = dbl(xs); return out[0]; }"
    )
    assert "static int dbl__gpuitem(int* xs, int __gpu_len_xs, int __gid)" in c_source
    assert (
        "static void dbl__gpucpu(int* xs, int __gpu_len_xs, int* __gpu_output, int __gpu_output_capacity, int __gpu_n)"
    ) in c_source
    assert "__gpu_output[__gid] = dbl__gpuitem" in c_source


def test_array_return_declaration_is_a_sized_readback_target() -> None:
    c_source = emit_c(
        "@gpu\nint[] dbl(int[] xs) { int i = gpu_id(); return xs[i] * 2; }\n"
        "int main() { int[] xs = {1, 2}; int[] out = dbl(xs); return out[0]; }"
    )
    length = re.search(
        r"int (__gpu_len_\d+);.*?\(\1 = \(sizeof\(xs\) / sizeof\(xs\[0\]\)\)\)",
        c_source,
        re.DOTALL,
    )
    assert length is not None
    length_name = length.group(1)
    declaration = "int out[((" + f"{length_name} > 0) ? {length_name} : 1)];"
    assert declaration in c_source
    prefix = _dispatch_prefixes(c_source)[0]
    assert f"btrc_gpu_read_buffer_checked({prefix}_gpu, {prefix}_buf_output, __gpu_output," in c_source
    assert re.search(
        rf"{prefix}_run\([^;]*, out, \(sizeof\(out\) / sizeof\(out\[0\]\)\)\)",
        c_source,
    )
    assert "int out[] = __gpu_result" not in c_source


def test_void_dispatch_falls_back_after_partial_setup_and_cleans_up(
    tmp_path: Path,
) -> None:
    executable = compile_with_gpu_stubs(
        tmp_path,
        "int gpu_stub_destroyed_buffers();\n"
        "@gpu\nvoid scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; }\n"
        "int main() { int[] xs = {1, 2}; scale(xs); "
        "return (xs[0] == 2 && xs[1] == 4 "
        "&& gpu_stub_destroyed_buffers() == 1) ? 0 : 1; }",
        available=True,
        fail_second_buffer=True,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_void_dispatch_falls_back_when_first_submission_is_rejected(
    tmp_path: Path,
) -> None:
    executable = compile_with_gpu_stubs(
        tmp_path,
        "@gpu void scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; } "
        "int main() { int[] xs = {2}; scale(xs); return xs[0] == 4 ? 0 : 1; }",
        available=True,
        fail_second_buffer=False,
        fail_dispatch_at=1,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


@pytest.mark.parametrize("fail_write_at", [1, 2])
def test_void_dispatch_falls_back_when_an_upload_is_rejected(tmp_path: Path, fail_write_at: int) -> None:
    """A rejected input or uniform upload fails setup; nothing dispatches on stale data."""
    executable = compile_with_gpu_stubs(
        tmp_path,
        "@gpu void scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; } "
        "int main() { int[] xs = {2}; scale(xs); return xs[0] == 4 ? 0 : 1; }",
        available=True,
        fail_second_buffer=False,
        fail_write_at=fail_write_at,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)
    c_source = emit_c(
        "@gpu void scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; } int main() { int[] xs = {2}; scale(xs); return 0; }"
    )
    assert "btrc_gpu_write_buffer(" in c_source
    assert not re.search(r"^\s*btrc_gpu_write_buffer\(", c_source, re.MULTILINE)


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_array_return_dispatch_falls_back_when_gpu_is_unavailable(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = compile_with_gpu_stubs(
        tmp_path,
        "@gpu\nint[] dbl(int[] xs) { int i = gpu_id(); return xs[i] * 2; }\n"
        "int main() { int[] xs = {1, 2}; int[] out = dbl(xs); "
        "return (out[0] == 2 && out[1] == 4) ? 0 : 1; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_cpu_fallback_early_return_is_per_invocation(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = compile_with_gpu_stubs(
        tmp_path,
        "@gpu void clamp(int[] xs) { int i = gpu_id(); "
        "if (xs[i] < 0) { return; } xs[i] *= 2; } "
        "int main() { int[] xs = {-3, 4, -1, 5}; clamp(xs); "
        "return (xs[0] == -3 && xs[1] == 8 && xs[2] == -1 "
        "&& xs[3] == 10) ? 0 : 1; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_hosted_macro_parameter_names_cross_gpu_host_and_cpu_paths(
    tmp_path: Path,
) -> None:
    source = (
        "@gpu void update(int[] stdin, int stdout, int stderr) { "
        "int i = gpu_id(); stdin[i] += stdout + stderr; } "
        "int main() { int[] values = {1}; "
        "update(stderr=3, stdin=values, stdout=2); "
        "return values[0] == 6 ? 0 : 1; }"
    )
    generated = emit_c(source)
    assert "__btrc_source_stdin" in generated
    assert "__btrc_source_stdout" in generated
    assert "__btrc_source_stderr" in generated
    executable = compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_cpu_fallback_array_return_handles_branches_and_whole_buffers(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = compile_with_gpu_stubs(
        tmp_path,
        "@gpu int[] clamp(int[] xs, int low, int high) { int i = gpu_id(); "
        "if (xs[i] < low) { return low; } "
        "if (xs[i] > high) { return high; } return xs; } "
        "int main() { int[] xs = {-3, 4, 12}; int[] out = clamp(xs, 0, 10); "
        "return (out[0] == 0 && out[1] == 4 && out[2] == 10) ? 0 : 1; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_dispatch_locals_are_unique_across_same_and_nested_scopes(
    tmp_path: Path,
) -> None:
    source = (
        "@gpu\nvoid scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; }\n"
        "@gpu\nvoid bump(int[] xs) { int i = gpu_id(); xs[i] += 1; }\n"
        "int main() { int[] xs = {1}; scale(xs); if (xs[0] == 2) { "
        "bump(xs); scale(xs); } return xs[0] == 6 ? 0 : 1; }"
    )
    c_source = emit_c(source)
    prefixes = _dispatch_prefixes(c_source)
    assert len(prefixes) == 3
    assert len(set(prefixes)) == 3
    executable = compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_loop_dispatch_keeps_one_persistent_context(tmp_path: Path) -> None:
    source = (
        "int gpu_stub_init_calls();\n"
        "@gpu\nvoid touch(int[] xs) { int i = gpu_id(); xs[i] += 1; }\n"
        "int main() { int[] xs = {1}; for (int i = 0; i < 3; i++) { "
        "touch(xs); } return gpu_stub_init_calls() == 1 ? 0 : 1; }"
    )
    c_source = emit_c(source)
    prefix = _dispatch_prefixes(c_source)[0]
    assert f"void* {prefix}_gpu = NULL;" in c_source
    assert f"{prefix}_gpu = btrc_gpu_acquire_compute();" in c_source
    executable = compile_with_gpu_stubs(
        tmp_path,
        source,
        available=True,
        fail_second_buffer=False,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_concurrent_dispatch_context_publication_destroys_cas_loser(
    tmp_path: Path,
) -> None:
    source = (
        "int gpu_stub_init_calls(); int gpu_stub_destroyed_contexts(); "
        "@gpu void touch(int[] xs) { int i = gpu_id(); xs[i] += 0; } "
        "int invoke() { int[] xs = {1}; touch(xs); return 0; } "
        "int main() { "
        "Thread<int> left = spawn(() => invoke()); "
        "Thread<int> right = spawn(() => invoke()); "
        "left.join(); right.join(); "
        "return (gpu_stub_init_calls() == 2 "
        "&& gpu_stub_destroyed_contexts() == 1) ? 0 : 1; }"
    )
    executable = compile_with_gpu_stubs(
        tmp_path,
        source,
        available=True,
        fail_second_buffer=False,
        init_barrier_count=2,
    )
    subprocess.run([str(executable)], check=True, timeout=15)


def test_collection_field_buffer_argument_uses_one_structured_temp() -> None:
    c_source = emit_c(
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } }\n"
        "class Holder { public Vector<int> values; "
        "public Holder(Vector<int> values) { self.values = values; } }\n"
        "@gpu\nvoid bump(int[] xs) { int i = gpu_id(); xs[i] += 1; }\n"
        "int main() { int[] raw = {1}; Vector<int> value = "
        "new Vector<int>(raw, 1); Holder holder = new Holder(value); "
        "bump(holder.values); return 0; }"
    )
    match = re.search(r"btrc_Vector_int\* (__gpu_arg_\d+);", c_source)
    assert match is not None
    temp = match.group(1)
    assert re.search(
        rf"\({temp} = (?:holder|__gpu_projection_root_\d+)->values\)",
        c_source,
    )
    assert f"{temp}->len" in c_source
    assert f"{temp}->data" in c_source
    assert "/* expr */" not in c_source


def test_collection_call_buffer_argument_evaluates_once_on_fallback(
    tmp_path: Path,
) -> None:
    source = (
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } }\n"
        "int calls = 0; Vector<int> acquire(Vector<int> value) { "
        "calls++; return value; }\n"
        "@gpu\nvoid bump(int[] xs) { int i = gpu_id(); xs[i] += 1; }\n"
        "int main() { int[] raw = {1, 2}; Vector<int> value = "
        "new Vector<int>(raw, 2); bump(acquire(value)); "
        "return (calls == 1 && raw[0] == 2 && raw[1] == 3) ? 0 : 1; }"
    )
    c_source = emit_c(source)
    assert c_source.count("acquire(value)") == 1
    assert "/* expr */" not in c_source
    executable = compile_with_gpu_stubs(
        tmp_path,
        source,
        available=True,
        fail_second_buffer=True,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_collection_argument_precedes_inferred_gpu_result_array() -> None:
    c_source = emit_c(
        "class Vector<T> { public T* data; public int len; "
        "public Vector(T* data, int len) { self.data = data; self.len = len; } }\n"
        "@gpu\nint[] copy(int[] xs) { int i = gpu_id(); return xs[i]; }\n"
        "int main() { int[] raw = {1}; Vector<int> value = "
        "new Vector<int>(raw, 1); int[] out = copy(value); return out[0]; }"
    )
    temp = re.search(r"btrc_Vector_int\* (__gpu_arg_\d+);", c_source)
    length = re.search(r"int (__gpu_len_\d+);", c_source)
    assert temp is not None
    assert length is not None
    assignment = f"({temp.group(1)} = value)"
    length_snapshot = f"({length.group(1)} = {temp.group(1)}->len)"
    declaration = "int out[((" + f"{length.group(1)} > 0) ? {length.group(1)} : 1)];"
    assert c_source.index(assignment) < c_source.index(length_snapshot)
    assert c_source.index(length_snapshot) < c_source.index(declaration)


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_mixed_parameter_order_uses_source_order_on_cpu_fallback(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = (
        "@gpu\nvoid mix(int bias, int[] xs, int factor, int[] ys) { "
        "int i = gpu_id(); xs[i] += bias; ys[i] += factor; }\n"
        "int main() { int[] xs = {1, 2}; int[] ys = {10, 20, 30}; "
        "mix(3, xs, 4, ys); return (xs[0] == 4 && xs[1] == 5 "
        "&& ys[0] == 14 && ys[1] == 24 && ys[2] == 30) ? 0 : 1; }"
    )
    c_source = emit_c(source)
    prefix = _dispatch_prefixes(c_source)[0]
    assert (
        f"static void {prefix}_run(int bias, int* xs, int __gpu_len_xs, int factor, int* ys, int __gpu_len_ys)"
    ) in c_source
    executable = compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True, timeout=RUN_TIMEOUT)


def test_output_kernel_in_arbitrary_expression_is_rejected() -> None:
    source = (
        "@gpu\nint[] dbl(int[] xs) { int i = gpu_id(); return xs[i] * 2; }\n"
        "int main() { int[] xs = {1, 2}; return dbl(xs)[0]; }"
    )
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    errors = SemanticAnalyzer().analyze(program).errors
    assert any(
        "only valid as an array declaration initializer or direct array assignment statement" in error
        for error in errors
    )


def _dispatch_prefixes(c_source: str) -> list[str]:
    return re.findall(r"void\* (__gpu_dispatch_\d+)_gpu = NULL;", c_source)
