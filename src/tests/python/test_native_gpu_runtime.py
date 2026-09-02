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
APP = ROOT / "src" / "stdlib" / "app"
HARNESS = ROOT / "src" / "tests" / "native" / "gpu_runtime_invalid.c"
SHADER_VALIDATION_HARNESS = ROOT / "src" / "tests" / "native" / "gpu_shader_validation.c"
SINGLETON_HARNESS = ROOT / "src" / "tests" / "native" / "gpu_compute_singleton.c"
_COMPILE_TIMEOUT_SECONDS = 120
_RUN_TIMEOUT_SECONDS = 90
_GPU_PROBE_PREAMBLE = "#include <btrc_gpu_compute_internal.h>\nextern bool btrc_gpu_available();\n"


def _compile_strict_c11(compiler: str, output: Path, sources: list[Path], flags: list[str]) -> None:
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
    command = [compiler, *flags, *strict, *map(str, sources), "-o", str(output)]
    subprocess.run(command, check=True, timeout=_COMPILE_TIMEOUT_SECONDS)


def _runtime_sources() -> list[str]:
    sources = [
        str(APP / "btrc_app.c"),
        str(GPU / "btrc_gpu.c"),
        str(GPU / "btrc_gpu_native_ui.c"),
        str(GPU / "btrc_gpu_native_ui_text.c"),
        str(GPU / "btrc_gpu_async.c"),
        str(GPU / "btrc_gpu_surface.c"),
    ]
    if sys.platform == "darwin":
        sources.append(str(GPU / "btrc_gpu_surface_macos.m"))
    return sources


def _compile_native_gpu_harness(tmp_path: Path, harness: Path, name: str) -> Path:
    cflags = os.environ.get("GPU_CFLAGS")
    ldflags = os.environ.get("GPU_LDFLAGS")
    if not cflags or not ldflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")

    executable = tmp_path / name
    subprocess.run(
        [
            os.environ.get("CC", "cc"),
            *shlex.split(cflags),
            "-DBTRC_GPU_WGPU_NATIVE",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{GPU}",
            f"-I{APP}",
            str(harness),
            *_runtime_sources(),
            *shlex.split(ldflags),
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        timeout=_COMPILE_TIMEOUT_SECONDS,
    )
    return executable


def test_compute_context_singleton_uses_c11_atomic_publication() -> None:
    runtime = (GPU / "btrc_gpu.c").read_text()
    publication = (GPU / "btrc_gpu_compute_singleton.h").read_text()

    assert '#include "btrc_gpu_compute_singleton.h"' in runtime
    assert "static _Atomic(void*) btrc_compute_singleton" in runtime
    assert "btrc_gpu_publish_compute_candidate(" in runtime
    assert "gpu_ == atomic_load_explicit(" in runtime
    assert "#include <stdatomic.h>" in publication
    assert "atomic_compare_exchange_strong_explicit(" in publication
    assert "destroy_candidate(candidate);" in publication


def test_render_context_borrows_the_application_surface() -> None:
    runtime = (GPU / "btrc_gpu.c").read_text()

    assert "std_app_surface_attach(surface_id, &lease)" in runtime
    assert "gpu->app_surface = lease;" in runtime
    assert "(void)std_app_surface_detach(gpu->app_surface);" in runtime
    assert "attach_failed:" in runtime
    assert "destroy_gpu_unchecked(gpu);" in runtime
    assert "wgpuSurfaceUnconfigure(gpu->surface);" in runtime
    assert runtime.index("wgpuSurfaceUnconfigure(gpu->surface);") < runtime.index("wgpuQueueRelease(gpu->queue)")
    assert "static unsigned long long active_render_gpu_id" in runtime
    assert "deviceLostCallbackInfo" in runtime
    assert "device_is_lost(gpu)" in runtime
    assert "glfwInit(" not in runtime
    assert "glfwCreateWindow(" not in runtime
    assert "btrc_gpu_window_create" not in runtime


def test_shader_creation_captures_backend_validation() -> None:
    runtime = (GPU / "btrc_gpu.c").read_text()
    interface = (GPU / "gpu.btrc").read_text()

    assert "uncapturedErrorCallbackInfo" in runtime
    assert "wgpuDevicePushErrorScope(gpu->device, WGPUErrorFilter_Validation);" in runtime
    assert "wgpuDevicePopErrorScope(" in runtime
    assert "return BTRC_GPU_RESOURCE_CREATION_FAILED;" in runtime
    assert "GPU_RESOURCE_CREATION_FAILED = 306" in interface


def test_headless_gpu_probe_is_quiet_when_no_adapter_exists() -> None:
    runtime = (GPU / "btrc_gpu.c").read_text()
    request_adapter = runtime[
        runtime.index("static bool request_adapter(") : runtime.index("static bool request_device(")
    ]
    request_device = runtime[
        runtime.index("static bool request_device(") : runtime.index("static bool device_is_lost(")
    ]

    assert "fprintf" not in request_adapter
    assert "fprintf" not in request_device
    assert 'fprintf(stderr, "[btrc-gpu] no suitable GPU adapter found' in runtime


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_compute_context_cas_publication_is_deterministic(tmp_path: Path, c_compiler: str) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"compute-singleton-{c_compiler}"
    _compile_strict_c11(c_compiler, executable, [SINGLETON_HARNESS], [f"-I{GPU}"])
    subprocess.run([str(executable)], check=True, timeout=_RUN_TIMEOUT_SECONDS)


def test_gpu_dispatch_abi_is_consistent() -> None:
    native_declarations = [
        (GPU / "btrc_gpu_compute_internal.h").read_text(),
        (GPU / "btrc_gpu.c").read_text(),
    ]
    for declaration in native_declarations:
        assert re.search(r"\bbool\s+btrc_gpu_dispatch\s*\(", declaration)
        assert re.search(r"\bvoid\s*\*\s*btrc_gpu_acquire_compute\s*\(", declaration)
        assert not re.search(r"\bvoid\s+btrc_gpu_dispatch\s*\(", declaration)

    public_header = (GPU / "btrc_gpu.h").read_text()
    public_module = (GPU / "gpu.btrc").read_text()
    assert "btrc_gpu_acquire_compute" not in public_header
    assert "void* btrc_gpu_" not in public_header
    assert "btrc_gpu_dispatch" not in public_module
    assert "btrc_gpu_acquire_compute" not in public_module
    assert "public void*" not in public_module


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_gpu_public_header_consumer_compiles_strict_c11(tmp_path: Path, c_compiler: str) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    consumer = tmp_path / "gpu_public_header_consumer.c"
    consumer.write_text(
        "#include <btrc_gpu.h>\n"
        "int consume(unsigned long long gpu, unsigned long long receipt) { "
        "return std_gpu_close(gpu, receipt); }\n"
    )
    _compile_strict_c11(
        c_compiler,
        tmp_path / f"gpu-consumer-{c_compiler}.o",
        [consumer],
        [f"-I{GPU}", "-c"],
    )


def test_gpu_runtime_rejects_invalid_inputs_without_a_display(tmp_path: Path) -> None:
    executable = _compile_native_gpu_harness(tmp_path, HARNESS, "gpu-invalid")
    environment = os.environ.copy()
    environment["BTRC_NO_GPU"] = "1"
    subprocess.run([str(executable)], check=True, env=environment, timeout=_RUN_TIMEOUT_SECONDS)


def test_native_gpu_rejects_malformed_wgsl_without_aborting(tmp_path: Path) -> None:
    executable = _compile_native_gpu_harness(tmp_path, SHADER_VALIDATION_HARNESS, "gpu-shader-validation")
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    if result.returncode == 77:
        pytest.skip("no native compute adapter is available")
    assert result.returncode == 0, result.stderr


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
    source = _GPU_PROBE_PREAMBLE + (
        f"@gpu void checked({scalar_type}[] xs, {scalar_type} divisor) "
        f"{{ int i = gpu_id(); {kernel_body} }}\n"
        "int main() { if (!btrc_gpu_available()) { return 77; } "
        f"{scalar_type}[] xs = {{{array_value}}}; checked(xs, {divisor}); return 0; }}"
    )
    executable = _compile_generated_gpu(tmp_path, source)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=_RUN_TIMEOUT_SECONDS)
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
    executable = _compile_generated_gpu(tmp_path, _GPU_PROBE_PREAMBLE + source)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=_RUN_TIMEOUT_SECONDS)
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
    subprocess.run([str(executable)], check=True, env=environment, timeout=_RUN_TIMEOUT_SECONDS)


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
            "-DBTRC_GPU_WGPU_NATIVE",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{GPU}",
            f"-I{APP}",
            str(unit),
            *_runtime_sources(),
            *shlex.split(ldflags),
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        timeout=_COMPILE_TIMEOUT_SECONDS,
    )
    return executable
