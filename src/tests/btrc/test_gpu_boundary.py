"""Production-driver tests for self-hosted @gpu lowering."""

from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
BTRCC_SOURCE = REPO / "src/compiler/btrc/btrcc_main.btrc"
FIXTURES = REPO / "src/tests/btrc/fixtures"
GPU_INCLUDE = REPO / "src/stdlib/gpu"
NAGA = shutil.which("naga")
if NAGA is None:
    shared_naga = Path("/tmp/btrc-naga-validator/bin/naga")
    if shared_naga.exists():
        NAGA = str(shared_naga)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not CC or shutil.which(CC[0]) is None,
    reason="requires a hosted C11 compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture(scope="module")
def btrcc_driver(tmp_path_factory) -> Path:
    """Build the real production self-host driver from the current sources."""
    output = tmp_path_factory.mktemp("selfhost-gpu-boundary")
    generated = output / "btrcc.c"
    binary = output / "btrcc"
    transpile = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(BTRCC_SOURCE),
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(output / "cache")},
        timeout=300,
    )
    assert transpile.returncode == 0 and generated.exists(), transpile.stderr
    compile_result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            str(generated),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=300,
    )
    assert compile_result.returncode == 0 and binary.exists(), compile_result.stderr
    return binary


def test_unused_gpu_kernel_is_proven_dead_and_erased(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    source = REPO / "src/tests/gpu/test_gpu_square.btrc"
    generated = _run([str(btrcc_driver), str(source)], timeout=120)

    assert generated.returncode == 0 and generated.stderr == ""
    assert all(marker not in generated.stdout for marker in ("squareElements", "gpu_id", "btrc_gpu", "wgsl"))

    c_path = tmp_path / "unused_gpu.c"
    binary = tmp_path / "unused_gpu"
    c_path.write_text(generated.stdout)
    compile_result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0
    assert executed.stdout == "PASS: test_gpu_square\n"


def _compile_with_stub(
    generated: str,
    tmp_path: Path,
    stub: str,
    *defines: str,
) -> Path:
    c_path = tmp_path / "generated.c"
    binary = tmp_path / "generated"
    c_path.write_text(generated)
    result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(f"-D{define}" for define in defines),
            f"-I{GPU_INCLUDE}",
            str(c_path),
            str(FIXTURES / stub),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


def _lower_fixture(btrcc_driver: Path, kind: str) -> str:
    result = _run(
        [
            str(btrcc_driver),
            "--no-stdlib",
            str(FIXTURES / f"gpu_called_{kind}.btrc"),
        ],
        timeout=120,
    )
    assert result.returncode == 0 and result.stderr == "", result.stderr
    return result.stdout


def _lower_source(btrcc_driver: Path, tmp_path: Path, source: str) -> str:
    source_path = tmp_path / "source.btrc"
    source_path.write_text(source)
    result = _run(
        [str(btrcc_driver), "--no-stdlib", str(source_path)],
        timeout=120,
    )
    assert result.returncode == 0 and result.stderr == "", result.stderr
    return result.stdout


def test_reachable_void_kernel_lowers_and_uses_checked_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    assert "struct BtrcStatus { code: atomic<u32>, }" in generated
    assert "btrc_gpu_read_buffer_checked" in generated
    assert generated.index("buf_status") < generated.index("status == 0U")
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_array_kernel_lowers_with_capacity_guard_and_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "array")
    assert "__gpu_output_capacity < __gpu_n" in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("status", "diagnostic"),
    [
        (1, "GPU array index out of bounds\n"),
        (2, "Division by zero\n"),
        (3, "Modulo by zero\n"),
        (4, "Integer division overflow\n"),
    ],
)
def test_checked_shader_status_cleans_up_then_exits_with_exact_diagnostic(
    btrcc_driver: Path,
    tmp_path: Path,
    status: int,
    diagnostic: str,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    cleanup = generated.index("btrc_gpu_buffer_destroy")
    failure = generated.index(f"status == {status}")
    assert cleanup < failure
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        f"STUB_STATUS_CODE={status}",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == diagnostic


def test_status_readback_failure_after_submit_cleans_up_and_fails_closed(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        "STUB_FAIL_READBACK=1",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == ("[btrc-gpu] GPU dispatch or result transfer failed after submission\n")


def test_dispatch_rejection_before_any_submit_uses_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        "STUB_DISPATCH_FAIL=1",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0
    assert result.stderr == ""


def test_unknown_shader_status_fails_closed_with_exact_diagnostic(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_fixture(btrcc_driver, "void")
    binary = _compile_with_stub(
        generated,
        tmp_path,
        "gpu_checked_stub.c",
        "STUB_STATUS_CODE=99",
    )
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == ("[btrc-gpu] GPU kernel reported an unknown failure status\n")


@pytest.mark.parametrize(
    ("operation", "divisor", "diagnostic"),
    [
        ("xs[i + 1] = 7", "1", "GPU array index out of bounds\n"),
        ("xs[i] = xs[i] / divisor", "0", "Division by zero\n"),
        ("xs[i] = xs[i] % divisor", "0", "Modulo by zero\n"),
        ("xs[i] = xs[i] / divisor", "-1", "Integer division overflow\n"),
    ],
)
def test_cpu_fallback_checked_failures_match_language_diagnostics(
    btrcc_driver: Path,
    tmp_path: Path,
    operation: str,
    divisor: str,
    diagnostic: str,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void checked(int[] xs, int divisor) { "
        f"int i = gpu_id(); {operation}; }} "
        "int main() { int[] xs = {-2147483648}; "
        f"checked(xs, {divisor}); return 0; }}",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 1
    assert result.stderr == diagnostic


def test_cpu_fallback_min_mod_minus_one_is_defined_zero(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void checked(int[] xs, int divisor) { int i = gpu_id(); "
        "xs[i] = xs[i] % divisor; } int main() { "
        "int[] xs = {-2147483648}; checked(xs, -1); return xs[0]; }",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_cpu_fallback_return_only_ends_the_current_invocation(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void early(int[] xs) { int i = gpu_id(); "
        "if (i == 0) { return; } xs[i] += 1; } int main() { "
        "int[] xs = {1, 2}; early(xs); "
        "return xs[0] == 1 && xs[1] == 3 ? 0 : 1; }",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


def test_contextual_float_results_match_wgsl_and_cpu_fallback(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void update(float[] xs, bool choose) { int i = gpu_id(); "
        "var adjusted = choose ? -(xs[i] + 1.0) : (float)sqrt(4.0f); "
        "xs[i] = adjusted; } int main() { float[] xs = {2.0f}; "
        "update(xs, true); return xs[0] == -3.0f ? 0 : 1; }",
    )
    match = re.search(r'static char\* update_wgsl = ("(?:\\.|[^"])*");', generated)
    assert match is not None
    shader = ast.literal_eval(match.group(1))
    assert "1.0f" not in shader
    assert "4.0f" not in shader
    assert "1.0" in shader and "sqrt(4.0)" in shader
    assert "1.0f" in generated and "sqrtf(4.0f)" in generated
    assert "float adjusted" in generated
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.parametrize("literal", ["1e100", "1e-50"])
def test_contextual_float_rejects_f32_overflow_and_underflow(
    btrcc_driver: Path,
    tmp_path: Path,
    literal: str,
) -> None:
    source = tmp_path / "invalid_gpu_float.btrc"
    source.write_text(
        "@gpu void invalid(float[] xs) { int i = gpu_id(); "
        f"xs[i] = {literal}; }} int main() {{ float[] xs = {{1.0f}}; "
        "invalid(xs); return 0; }"
    )
    result = _run([str(btrcc_driver), "--no-stdlib", str(source)], timeout=120)
    assert result.returncode == 1
    assert "floating literal is outside the WGSL f32 range" in result.stderr


def test_named_and_default_gpu_arguments_preserve_declared_parameter_order(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void affine(int[] xs, int scale = 2, int bias = 1) { "
        "int i = gpu_id(); xs[i] = xs[i] * scale + bias; } "
        "int main() { int[] xs = {4}; affine(xs, bias=3); "
        "return xs[0] == 11 ? 0 : 1; }",
    )
    binary = _compile_with_stub(generated, tmp_path, "gpu_unavailable_stub.c")
    result = _run([str(binary)], timeout=15)
    assert result.returncode == 0


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_selfhost_checked_shader_validates_with_naga(
    btrcc_driver: Path,
) -> None:
    result = _run(
        [
            str(btrcc_driver),
            "--no-stdlib",
            str(FIXTURES / "gpu_checked_semantics.btrc"),
        ],
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(
        r'static char\* checked_wgsl = ("(?:\\.|[^"])*");',
        result.stdout,
    )
    assert match is not None
    shader = ast.literal_eval(match.group(1))
    validated = subprocess.run(
        [NAGA, "--stdin-file-path", "generated.wgsl"],
        input=shader,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stderr


@pytest.mark.skipif(NAGA is None, reason="naga WGSL validator is not installed")
def test_selfhost_compound_assignment_shader_validates_with_naga(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _lower_source(
        btrcc_driver,
        tmp_path,
        "@gpu void compound(int[] xs, bool toggle) { int i = gpu_id(); "
        "int shift = 1; bool flag = toggle; xs[i] <<= shift; flag ^= true; "
        "xs[i] /= 2; xs[i] %= 3; } int main() { int[] xs = {8}; "
        "compound(xs, true); return 0; }",
    )
    match = re.search(r'static char\* compound_wgsl = ("(?:\\.|[^"])*");', generated)
    assert match is not None
    shader = ast.literal_eval(match.group(1))
    assert "u32(" in shader
    assert " != true" in shader
    assert "atomicMax(&btrc_status.code, 2u)" in shader
    assert "atomicMax(&btrc_status.code, 3u)" in shader
    validated = subprocess.run(
        [NAGA, "--stdin-file-path", "generated.wgsl"],
        input=shader,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stderr


def test_float_remainder_assignment_fails_closed(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_gpu.btrc"
    source.write_text("@gpu void invalid(float[] xs) { int i = gpu_id(); xs[i] %= 2.0; } int main() { return 0; }")
    result = _run([str(btrcc_driver), "--no-stdlib", str(source)], timeout=120)
    assert result.returncode == 1
    assert "GPU remainder assignment requires integer operands" in result.stderr
