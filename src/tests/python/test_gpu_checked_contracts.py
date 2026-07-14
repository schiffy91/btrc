"""Host-visible checked arithmetic and bounds contracts for GPU kernels."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.gpu_errors import (
    GPU_STATUS_MESSAGES,
    GPU_TRANSFER_FAILURE_MESSAGE,
    GPU_UNKNOWN_STATUS_MESSAGE,
)
from src.compiler.python.ir.optimizer_walk import iter_ir_nodes
from src.tests.python.test_codegen import emit_c
from src.tests.python.test_gpu_dispatch_failures import (
    COMPILERS,
    _compile_with_gpu_stubs,
)
from src.tests.python.test_gpu_dispatch_ir import _generate


def test_shader_declares_lengths_and_final_atomic_status_binding() -> None:
    module = _generate(
        "@gpu int[] checked(int[] xs, int[] ys, int divisor) { int i = gpu_id(); "
        "return xs[i] / divisor + ys[i] % divisor; } "
        "int main() { int[] xs = {4}; int[] ys = {3}; int[] out = checked(xs, ys, 2); return out[0]; }"
    )
    [kernel] = module.gpu_kernels

    assert kernel.status_binding == 4
    assert "btrc_len_0: i32," in kernel.wgsl_source
    assert "btrc_len_1: i32," in kernel.wgsl_source
    assert "struct BtrcStatus { code: atomic<u32>, }" in kernel.wgsl_source
    assert "@group(0) @binding(4) var<storage, read_write> btrc_status" in kernel.wgsl_source
    for code in GPU_STATUS_MESSAGES:
        assert f"atomicMax(&btrc_status.code, {code}u)" in kernel.wgsl_source
    assert not any(type(node).__name__.startswith("IRRaw") for node in iter_ir_nodes(module))


def test_dispatch_reads_status_before_guarded_user_data_and_cleans_before_failure() -> None:
    c_source = emit_c(
        "@gpu void checked(int[] xs, int divisor) { int i = gpu_id(); xs[i] /= divisor; } "
        "int main() { int[] xs = {4}; checked(xs, 2); return xs[0]; }"
    )
    status_read = re.search(
        r"btrc_gpu_read_buffer_checked\([^;]+buf_status[^;]+status[^;]+\)",
        c_source,
    )
    assert status_read is not None
    clear_guard = c_source.index("status == 0U", status_read.start())
    user_read = c_source.index("btrc_gpu_read_buffer_checked", clear_guard)
    status_cleanup = c_source.index("btrc_gpu_buffer_destroy", user_read)
    checked_failure = c_source.index("status != 0U", status_cleanup)
    assert status_read.start() < clear_guard < user_read < status_cleanup < checked_failure


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("status_code", sorted(GPU_STATUS_MESSAGES))
def test_host_status_codes_fail_with_exact_language_diagnostic(
    tmp_path: Path,
    c_compiler: str,
    status_code: int,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void checked(int[] xs) { int i = gpu_id(); xs[i] += 1; } "
        "int main() { int[] xs = {1}; checked(xs); return 0; }",
        available=True,
        fail_second_buffer=False,
        status_code=status_code,
        compiler=c_compiler,
    )

    result = subprocess.run([str(executable)], capture_output=True, text=True)

    assert result.returncode == 1
    assert result.stderr == GPU_STATUS_MESSAGES[status_code]


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_unknown_host_status_has_a_generic_diagnostic(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void checked(int[] xs) { int i = gpu_id(); xs[i] += 1; } "
        "int main() { int[] xs = {1}; checked(xs); return 0; }",
        available=True,
        fail_second_buffer=False,
        status_code=99,
        compiler=c_compiler,
    )

    result = subprocess.run([str(executable)], capture_output=True, text=True)

    assert result.returncode == 1
    assert result.stderr == GPU_UNKNOWN_STATUS_MESSAGE


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    ("kernel_body", "diagnostic"),
    [
        ("xs[i + 1] = 7;", GPU_STATUS_MESSAGES[1]),
        ("xs[i] = xs[i] / divisor;", GPU_STATUS_MESSAGES[2]),
        ("xs[i] = xs[i] % divisor;", GPU_STATUS_MESSAGES[3]),
    ],
)
def test_cpu_fallback_uses_the_same_checked_failure_contract(
    tmp_path: Path,
    c_compiler: str,
    kernel_body: str,
    diagnostic: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        f"@gpu void checked(int[] xs, int divisor) {{ int i = gpu_id(); {kernel_body} }} "
        "int main() { int[] xs = {4}; checked(xs, 0); return 0; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )

    result = subprocess.run([str(executable)], capture_output=True, text=True)

    assert result.returncode == 1
    assert result.stderr == diagnostic


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cpu_fallback_min_mod_minus_one_is_defined_zero(tmp_path: Path, c_compiler: str) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void checked(int[] xs, int divisor) { int i = gpu_id(); xs[i] %= divisor; } "
        "int main() { int[] xs = {-2147483648}; checked(xs, -1); return xs[0]; }",
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    subprocess.run([str(executable)], check=True)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_status_readback_failure_after_submission_fails_closed(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void bump(int[] xs) { int i = gpu_id(); xs[i] += 1; } "
        "int main() { int[] xs = {1}; bump(xs); return xs[0] == 2 ? 0 : 1; }",
        available=True,
        fail_second_buffer=False,
        fail_readback=True,
        compiler=c_compiler,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True)

    assert result.returncode == 1
    assert result.stderr == GPU_TRANSFER_FAILURE_MESSAGE


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_partial_multi_buffer_readback_never_runs_cpu_fallback(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        "@gpu void bump(int[] xs, int[] ys) { int i = gpu_id(); "
        "xs[i] += 1; ys[i] += 1; } "
        "int main() { int[] xs = {1}; int[] ys = {2}; bump(xs, ys); return 0; }",
        available=True,
        fail_second_buffer=False,
        mutate_readback_at=2,
        fail_readback_at=3,
        compiler=c_compiler,
    )

    result = subprocess.run([str(executable)], capture_output=True, text=True)

    assert result.returncode == 1
    assert result.stderr == GPU_TRANSFER_FAILURE_MESSAGE


NAGA = shutil.which("naga")


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_checked_shader_validates_with_naga() -> None:
    module = _generate(
        "@gpu int[] checked(int[] xs, int divisor) { int i = gpu_id(); "
        "return xs[i + 1] / divisor + xs[i] % divisor; } int main() { return 0; }"
    )
    [kernel] = module.gpu_kernels
    result = subprocess.run(
        [NAGA, "--stdin-file-path", "checked.wgsl"],
        input=kernel.wgsl_source,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
