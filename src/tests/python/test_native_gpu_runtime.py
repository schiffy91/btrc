import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

ROOT = Path(__file__).resolve().parents[3]
GPU = ROOT / "src" / "stdlib" / "gpu"
HARNESS = ROOT / "src" / "tests" / "native" / "gpu_runtime_invalid.c"
SINGLETON_HARNESS = ROOT / "src" / "tests" / "native" / "gpu_compute_singleton.c"


def _runtime_sources() -> list[str]:
    sources = [str(GPU / "btrc_gpu.c")]
    if sys.platform == "darwin":
        sources.append(str(GPU / "btrc_gpu_surface_macos.m"))
    return sources


def test_compute_context_singleton_uses_c11_atomic_publication() -> None:
    runtime = (GPU / "btrc_gpu.c").read_text()
    publication = (GPU / "btrc_gpu_compute_singleton.h").read_text()

    assert '#include "btrc_gpu_compute_singleton.h"' in runtime
    assert "static _Atomic(void*) btrc_compute_singleton" in runtime
    assert "btrc_gpu_publish_compute_candidate(" in runtime
    assert "#include <stdatomic.h>" in publication
    assert "atomic_compare_exchange_strong_explicit(" in publication
    assert "destroy_candidate(candidate);" in publication


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_compute_context_cas_publication_is_deterministic(tmp_path: Path, c_compiler: str) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"compute-singleton-{c_compiler}"
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{GPU}",
            str(SINGLETON_HARNESS),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_gpu_dispatch_abi_is_consistent() -> None:
    declarations = [
        (GPU / "btrc_gpu.h").read_text(),
        (GPU / "gpu.btrc").read_text(),
        (GPU / "btrc_gpu.c").read_text(),
    ]
    for declaration in declarations:
        assert re.search(r"\bbool\s+btrc_gpu_dispatch\s*\(", declaration)
        assert re.search(r"\bvoid\s*\*\s*btrc_gpu_acquire_compute\s*\(", declaration)
        assert not re.search(r"\bvoid\s+btrc_gpu_dispatch\s*\(", declaration)


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_gpu_public_header_consumer_compiles_strict_c11(tmp_path: Path, c_compiler: str) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{GPU}",
            "-c",
            str(HARNESS),
            "-o",
            str(tmp_path / f"gpu-consumer-{c_compiler}.o"),
        ],
        check=True,
    )


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_gpu_runtime_core_compiles_strict_c11(tmp_path: Path, c_compiler: str) -> None:
    cflags = os.environ.get("GPU_CFLAGS")
    if not cflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    subprocess.run(
        [
            c_compiler,
            *shlex.split(cflags),
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{GPU}",
            "-O2",
            "-c",
            str(GPU / "btrc_gpu.c"),
            "-o",
            str(tmp_path / f"gpu-runtime-{c_compiler}.o"),
        ],
        check=True,
    )


def test_gpu_runtime_rejects_invalid_inputs_without_a_display(tmp_path: Path) -> None:
    cflags = os.environ.get("GPU_CFLAGS")
    ldflags = os.environ.get("GPU_LDFLAGS")
    if not cflags or not ldflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")

    executable = tmp_path / "gpu-invalid"
    subprocess.run(
        [
            os.environ.get("CC", "cc"),
            *shlex.split(cflags),
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{GPU}",
            str(HARNESS),
            *_runtime_sources(),
            *shlex.split(ldflags),
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
    )
    environment = os.environ.copy()
    environment["BTRC_NO_GPU"] = "1"
    subprocess.run([str(executable)], check=True, env=environment)


@pytest.mark.parametrize(
    ("scalar_type", "array_value", "divisor", "kernel_body", "diagnostic"),
    [
        ("int", "4", "0", "xs[i] = xs[i] / divisor;", "Division by zero\n"),
        ("float", "4.0", "0.0", "xs[i] = xs[i] / divisor;", "Division by zero\n"),
        ("int", "4", "0", "xs[i] = xs[i] % divisor;", "Modulo by zero\n"),
        (
            "int",
            "-2147483648",
            "-1",
            "xs[i] = xs[i] / divisor;",
            "Integer division overflow\n",
        ),
        ("int", "4", "1", "xs[i + 1] = 7;", "GPU array index out of bounds\n"),
    ],
)
def test_native_gpu_reports_checked_kernel_failures_when_available(
    tmp_path: Path,
    scalar_type: str,
    array_value: str,
    divisor: str,
    kernel_body: str,
    diagnostic: str,
) -> None:
    source = (
        "#include <btrc_gpu.h>\n"
        f"@gpu void checked({scalar_type}[] xs, {scalar_type} divisor) "
        f"{{ int i = gpu_id(); {kernel_body} }}\n"
        "int main() { if (!btrc_gpu_available()) { return 77; } "
        f"{scalar_type}[] xs = {{{array_value}}}; checked(xs, {divisor}); return 0; }}"
    )
    executable = _compile_generated_gpu(tmp_path, source)
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    if result.returncode == 77:
        pytest.skip("no native compute adapter is available")
    assert result.returncode == 1
    assert result.stderr.endswith(diagnostic)


@pytest.mark.parametrize(
    "source",
    [
        "@gpu void checked(int[] xs, int divisor) { int i = gpu_id(); xs[i] %= divisor; } "
        "int main() { if (!btrc_gpu_available()) { return 77; } "
        "int[] xs = {-2147483648}; checked(xs, -1); return xs[0] == 0 ? 0 : 1; }",
        "@gpu int[] doubled(int[] xs) { int i = gpu_id(); return xs[i] * 2; } "
        "int main() { if (!btrc_gpu_available()) { return 77; } "
        "int[] xs = {4}; int[] out = doubled(xs); return out[0] == 8 ? 0 : 1; }",
        "@gpu void compound(int[] xs, int shift, bool right) { int i = gpu_id(); "
        "xs[i] <<= shift; xs[i] >>= shift; bool flag = true; flag ^= right; "
        "if (flag) { xs[i] |= 1; } } "
        "int main() { if (!btrc_gpu_available()) { return 77; } "
        "int[] xs = {4}; compound(xs, 1, false); return xs[0] == 5 ? 0 : 1; }",
    ],
)
def test_native_gpu_checked_success_paths_when_available(tmp_path: Path, source: str) -> None:
    executable = _compile_generated_gpu(tmp_path, "#include <btrc_gpu.h>\n" + source)
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    if result.returncode == 77:
        pytest.skip("no native compute adapter is available")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "@gpu void clamp(int[] xs) { int i = gpu_id(); "
        "if (xs[i] < 0) { return; } xs[i] *= 2; } "
        "int main() { int[] xs = {-3, 4, -1, 5}; clamp(xs); "
        "return (xs[0] == -3 && xs[1] == 8 && xs[2] == -1 "
        "&& xs[3] == 10) ? 0 : 1; }",
        "@gpu int[] clamp(int[] xs, int low, int high) { int i = gpu_id(); "
        "if (xs[i] < low) { return low; } "
        "if (xs[i] > high) { return high; } return xs; } "
        "int main() { int[] xs = {-3, 4, 12}; int[] out = clamp(xs, 0, 10); "
        "return (out[0] == 0 && out[1] == 4 && out[2] == 10) ? 0 : 1; }",
    ],
)
def test_native_gpu_cpu_fallback_when_explicitly_disabled(
    tmp_path: Path,
    source: str,
) -> None:
    executable = _compile_generated_gpu(tmp_path, "#include <btrc_gpu.h>\n" + source)
    environment = {**os.environ, "BTRC_NO_GPU": "1"}
    subprocess.run([str(executable)], check=True, env=environment)


def _compile_generated_gpu(tmp_path: Path, source: str) -> Path:
    cflags = os.environ.get("GPU_CFLAGS")
    ldflags = os.environ.get("GPU_LDFLAGS")
    if not cflags or not ldflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")
    unit = tmp_path / "checked_gpu.c"
    unit.write_text(emit_c(source))
    executable = tmp_path / "checked-gpu"
    subprocess.run(
        [
            os.environ.get("CC", "cc"),
            *shlex.split(cflags),
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{GPU}",
            str(unit),
            *_runtime_sources(),
            *shlex.split(ldflags),
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
    )
    return executable
