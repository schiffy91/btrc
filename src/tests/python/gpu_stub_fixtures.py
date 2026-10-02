"""Compile reference-compiler @gpu output against stubbed WebGPU declarations."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.reference_pipeline import emit_c

GPU_INCLUDE = Path(__file__).resolve().parents[2] / "runtime" / "gpu"


GPU_DECLS = r"""
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
bool btrc_gpu_write_buffer(void*, void*, void*, int);
bool btrc_gpu_read_buffer_checked(void*, void*, void*, int);
void btrc_gpu_buffer_destroy(void*);
void* btrc_gpu_create_shader(void*, char*);
void btrc_gpu_shader_destroy(void*);
void* btrc_gpu_create_compute_pipeline(void*, void*, char*);
void btrc_gpu_compute_pipeline_destroy(void*);
void* btrc_gpu_create_bind_group(void*, void*, void**, int);
void btrc_gpu_bind_group_destroy(void*);
bool btrc_gpu_dispatch(void*, void*, void*, int);
"""


GPU_STUBS = r"""
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
bool btrc_gpu_write_buffer(void* gpu, void* buffer, void* data, int size) {
    (void)gpu; (void)buffer; (void)data; (void)size;
    static atomic_int write_calls;
    int call = atomic_fetch_add(&write_calls, 1) + 1;
    return STUB_FAIL_WRITE_AT == 0 || call != STUB_FAIL_WRITE_AT;
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


def compile_with_gpu_stubs(
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
    fail_write_at: int = 0,
    init_barrier_count: int = 0,
    compiler: str | None = None,
) -> Path:
    compiler = compiler or shutil.which(os.environ.get("CC", "cc"))
    if compiler is None:
        pytest.skip("a C compiler is required")
    unit = tmp_path / "gpu_dispatch.c"
    unit.write_text(
        GPU_DECLS
        + f"\n#define STUB_AVAILABLE {int(available)}\n"
        + f"#define STUB_FAIL_SECOND_BUFFER {int(fail_second_buffer)}\n"
        + f"#define STUB_STATUS_CODE {status_code}\n"
        + f"#define STUB_FAIL_READBACK_AT {1 if fail_readback else fail_readback_at}\n"
        + f"#define STUB_MUTATE_READBACK_AT {mutate_readback_at}\n"
        + f"#define STUB_FAIL_DISPATCH_AT {fail_dispatch_at}\n"
        + f"#define STUB_FAIL_WRITE_AT {fail_write_at}\n"
        + f"#define STUB_INIT_BARRIER_COUNT {init_barrier_count}\n"
        + emit_c(source)
        + GPU_STUBS
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
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT)
    return executable
