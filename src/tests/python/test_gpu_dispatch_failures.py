"""Failure-path contracts for generated @gpu compute dispatches."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
GPU_INCLUDE = Path(__file__).resolve().parents[2] / "stdlib" / "gpu"

_GPU_DECLS = r"""
#include <stdbool.h>
#include <stdatomic.h>
#include <stdlib.h>
#define BTRC_GPU_STORAGE 0x80
#define BTRC_GPU_UNIFORM 0x40
#define BTRC_GPU_COPY_DST 0x08
#define BTRC_GPU_COPY_SRC 0x04
bool btrc_gpu_available(void);
void* btrc_gpu_init_compute(void);
void* btrc_gpu_acquire_compute(void);
void btrc_gpu_destroy(void*);
void* btrc_gpu_create_buffer(void*, int, int);
void btrc_gpu_write_buffer(void*, void*, void*, int);
bool btrc_gpu_read_buffer_checked(void*, void*, void*, int);
void btrc_gpu_read_buffer(void*, void*, void*, int);
void btrc_gpu_buffer_destroy(void*);
void* btrc_gpu_create_shader(void*, char*);
void btrc_gpu_shader_destroy(void*);
void* btrc_gpu_create_compute_pipeline(void*, void*, char*);
void btrc_gpu_compute_pipeline_destroy(void*);
void* btrc_gpu_create_bind_group(void*, void*, void**, int);
void btrc_gpu_bind_group_destroy(void*);
bool btrc_gpu_dispatch(void*, void*, void*, int);
"""


_GPU_STUBS = r"""
static char stub_buffer;
static char stub_shader;
static char stub_pipeline;
static char stub_bind_group;
static atomic_int stub_buffer_calls;
static atomic_int stub_destroyed_buffers;
static atomic_int stub_destroyed_contexts;
static atomic_int stub_init_calls;
static atomic_int stub_read_calls;
static _Atomic(void*) stub_cached_gpu;

void* btrc_gpu_init_compute(void) {
    int call = atomic_fetch_add(&stub_init_calls, 1) + 1;
    if (STUB_INIT_BARRIER_COUNT > 0 && call <= STUB_INIT_BARRIER_COUNT) {
        while (atomic_load_explicit(
                &stub_init_calls, memory_order_acquire)
                < STUB_INIT_BARRIER_COUNT) { }
    }
    return malloc(1);
}
void btrc_gpu_destroy(void* gpu) {
    if (gpu) {
        atomic_fetch_add(&stub_destroyed_contexts, 1);
        free(gpu);
    }
}
void* btrc_gpu_acquire_compute(void) {
    if (!STUB_AVAILABLE) { return NULL; }
    void* current = atomic_load_explicit(&stub_cached_gpu, memory_order_acquire);
    if (current) { return current; }
    void* candidate = btrc_gpu_init_compute();
    void* expected = NULL;
    if (atomic_compare_exchange_strong_explicit(
            &stub_cached_gpu, &expected, candidate,
            memory_order_release, memory_order_acquire)) {
        return candidate;
    }
    btrc_gpu_destroy(candidate);
    return expected;
}
bool btrc_gpu_available(void) { return btrc_gpu_acquire_compute() != NULL; }
void* btrc_gpu_create_buffer(void* gpu, int size, int usage) {
    (void)gpu; (void)size; (void)usage;
    int call = atomic_fetch_add(&stub_buffer_calls, 1) + 1;
    if (STUB_FAIL_SECOND_BUFFER && call == 2) { return NULL; }
    return &stub_buffer;
}
void btrc_gpu_write_buffer(void* gpu, void* buffer, void* data, int size) {
    (void)gpu; (void)buffer; (void)data; (void)size;
}
bool btrc_gpu_read_buffer_checked(void* gpu, void* buffer, void* data, int size) {
    (void)gpu; (void)buffer;
    int read_call = atomic_fetch_add(&stub_read_calls, 1) + 1;
    if (STUB_FAIL_READBACK_AT == read_call) { return false; }
    if (read_call == 1 && STUB_STATUS_CODE != 0
            && size == (int)sizeof(uint32_t)) {
        uint32_t status = (uint32_t)STUB_STATUS_CODE;
        memcpy(data, &status, sizeof(status));
    }
    if (STUB_MUTATE_READBACK_AT == read_call && size >= (int)sizeof(int)) {
        ((int*)data)[0] = 41;
    }
    return true;
}
void btrc_gpu_read_buffer(void* gpu, void* buffer, void* data, int size) {
    (void)btrc_gpu_read_buffer_checked(gpu, buffer, data, size);
}
void btrc_gpu_buffer_destroy(void* buffer) {
    if (buffer) { atomic_fetch_add(&stub_destroyed_buffers, 1); }
}
void* btrc_gpu_create_shader(void* gpu, char* source) {
    (void)gpu; (void)source; return &stub_shader;
}
void btrc_gpu_shader_destroy(void* shader) { (void)shader; }
void* btrc_gpu_create_compute_pipeline(void* gpu, void* shader, char* entry) {
    (void)gpu; (void)shader; (void)entry; return &stub_pipeline;
}
void btrc_gpu_compute_pipeline_destroy(void* pipeline) { (void)pipeline; }
void* btrc_gpu_create_bind_group(
    void* gpu, void* pipeline, void** buffers, int count
) {
    (void)gpu; (void)pipeline; (void)buffers; (void)count;
    return &stub_bind_group;
}
void btrc_gpu_bind_group_destroy(void* bind_group) { (void)bind_group; }
bool btrc_gpu_dispatch(void* gpu, void* pipeline, void* bind_group, int count) {
    (void)gpu; (void)pipeline; (void)bind_group; (void)count;
    static atomic_int dispatch_calls;
    int call = atomic_fetch_add(&dispatch_calls, 1) + 1;
    return STUB_FAIL_DISPATCH_AT == 0 || call != STUB_FAIL_DISPATCH_AT;
}
int gpu_stub_destroyed_buffers(void) { return atomic_load(&stub_destroyed_buffers); }
int gpu_stub_destroyed_contexts(void) { return atomic_load(&stub_destroyed_contexts); }
int gpu_stub_init_calls(void) { return atomic_load(&stub_init_calls); }
"""


def _compile_with_gpu_stubs(
    tmp_path: Path,
    source: str,
    *,
    available: bool,
    fail_second_buffer: bool,
    status_code: int = 0,
    fail_readback: bool = False,
    fail_readback_at: int = 0,
    mutate_readback_at: int = 0,
    fail_dispatch_at: int = 0,
    init_barrier_count: int = 0,
    compiler: str | None = None,
) -> Path:
    compiler = compiler or shutil.which(os.environ.get("CC", "cc"))
    if compiler is None:
        pytest.skip("a C compiler is required")
    unit = tmp_path / "gpu_dispatch.c"
    unit.write_text(
        _GPU_DECLS
        + f"\n#define STUB_AVAILABLE {int(available)}\n"
        + f"#define STUB_FAIL_SECOND_BUFFER {int(fail_second_buffer)}\n"
        + f"#define STUB_STATUS_CODE {status_code}\n"
        + f"#define STUB_FAIL_READBACK_AT {1 if fail_readback else fail_readback_at}\n"
        + f"#define STUB_MUTATE_READBACK_AT {mutate_readback_at}\n"
        + f"#define STUB_FAIL_DISPATCH_AT {fail_dispatch_at}\n"
        + f"#define STUB_INIT_BARRIER_COUNT {init_barrier_count}\n"
        + emit_c(source)
        + _GPU_STUBS
    )
    executable = tmp_path / "gpu_dispatch"
    command = [
        compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        f"-I{GPU_INCLUDE}",
        str(unit),
        "-lm",
    ]
    if "pthread.h" in unit.read_text():
        command.append("-lpthread")
    command.extend(["-o", str(executable)])
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return executable


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
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "int gpu_stub_destroyed_buffers();\n"
        "@gpu\nvoid scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; }\n"
        "int main() { int[] xs = {1, 2}; scale(xs); "
        "return (xs[0] == 2 && xs[1] == 4 "
        "&& gpu_stub_destroyed_buffers() == 1) ? 0 : 1; }",
        available=True,
        fail_second_buffer=True,
    )
    subprocess.run([str(executable)], check=True)


def test_void_dispatch_falls_back_when_first_submission_is_rejected(
    tmp_path: Path,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; } "
        "int main() { int[] xs = {2}; scale(xs); return xs[0] == 4 ? 0 : 1; }",
        available=True,
        fail_second_buffer=False,
        fail_dispatch_at=1,
    )
    subprocess.run([str(executable)], check=True)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_array_return_dispatch_falls_back_when_gpu_is_unavailable(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu\nint[] dbl(int[] xs) { int i = gpu_id(); return xs[i] * 2; }\n"
        "int main() { int[] xs = {1, 2}; int[] out = dbl(xs); "
        "return (out[0] == 2 && out[1] == 4) ? 0 : 1; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cpu_fallback_early_return_is_per_invocation(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
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
    subprocess.run([str(executable)], check=True)


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
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
    )
    subprocess.run([str(executable)], check=True)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cpu_fallback_array_return_handles_branches_and_whole_buffers(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
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
    subprocess.run([str(executable)], check=True)


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
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
    )
    subprocess.run([str(executable)], check=True)


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
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=True,
        fail_second_buffer=False,
    )
    subprocess.run([str(executable)], check=True)


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
    executable = _compile_with_gpu_stubs(
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
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=True,
        fail_second_buffer=True,
    )
    subprocess.run([str(executable)], check=True)


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


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
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
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True)


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
