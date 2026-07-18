import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GPU = ROOT / "src" / "stdlib" / "gpu"
ASYNC_FIXTURE = ROOT / "src" / "tests" / "native" / "gpu_async"
RUNTIME_SOURCES = ["btrc_gpu.c", "btrc_gpu_async.c", "btrc_gpu_surface.c"]
_COMPILE_TIMEOUT_SECONDS = 120
_RUN_TIMEOUT_SECONDS = 90


def _compile_strict_c11(compiler: str, output: Path, sources: list[Path], flags: list[str]) -> None:
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
    command = [compiler, *flags, *strict, *map(str, sources), "-o", str(output)]
    subprocess.run(command, check=True, timeout=_COMPILE_TIMEOUT_SECONDS)


def test_gpu_async_backend_contracts_are_explicit() -> None:
    runtime = (GPU / "btrc_gpu.c").read_text()
    async_header = (GPU / "btrc_gpu_async.h").read_text()
    async_runtime = (GPU / "btrc_gpu_async.c").read_text()

    assert "wgpuCreateInstance(NULL)" in runtime
    assert "timedWaitAnyEnable" not in runtime
    assert runtime.count("BTRC_GPU_ASYNC_CALLBACK_MODE") == 3
    assert "WGPUCallbackMode_WaitAnyOnly" in async_header
    assert "WGPUCallbackMode_AllowProcessEvents" in async_header
    assert "btrc_gpu_async_wait(" in runtime
    assert "wgpuInstanceWaitAny(" in async_runtime
    assert "wgpuInstanceProcessEvents(instance)" in async_runtime
    assert "static atomic_flag event_pump" in async_runtime
    assert "instance, 1, &wait_info, 0" in async_runtime
    assert "now - start >= timeout_ns" in async_runtime
    assert ".userdata2 = staging" in runtime
    assert "gpu_async_cancel_drain_timeout_ns" in runtime


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
@pytest.mark.parametrize(
    ("backend", "backend_flags"),
    [("conforming", []), ("wgpu-native", ["-DBTRC_GPU_WGPU_NATIVE"])],
)
def test_gpu_async_state_machine(
    tmp_path: Path,
    c_compiler: str,
    backend: str,
    backend_flags: list[str],
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"gpu-async-{backend}-{c_compiler}"
    _compile_strict_c11(
        c_compiler,
        executable,
        [
            ASYNC_FIXTURE / "gpu_async_state_machine.c",
            ASYNC_FIXTURE / "fake_webgpu_runtime.c",
            GPU / "btrc_gpu_async.c",
        ],
        [*backend_flags, f"-I{ASYNC_FIXTURE}", f"-I{GPU}", "-pthread"],
    )
    subprocess.run([str(executable)], check=True, timeout=_RUN_TIMEOUT_SECONDS)


def test_gpu_archive_rule_asserts_runtime_membership() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "GPU_BACKEND_CFLAGS ?= -DBTRC_GPU_WGPU_NATIVE" in makefile
    archive_cleanup = makefile.index('rm -f "$$D/build/libbtrc_gpu.a"')
    dependency_probe = makefile.index("for source in btrc_gpu.c btrc_gpu_async.c btrc_gpu_surface.c")
    assert archive_cleanup < dependency_probe
    assert '-E "$$D/$$source" -o /dev/null' in makefile
    assert '-E "$$D/btrc_gpu_surface_macos.m" -o /dev/null' in makefile
    assert "btrc_gpu_async.o $$D/build/btrc_gpu_surface.o" in makefile
    assert r'grep -q "btrc_gpu_async\\.o$$"' in makefile
    assert r'grep -q "btrc_gpu_surface\\.o$$"' in makefile


def test_surface_bridge_has_windows_and_linux_implementations() -> None:
    surface = (GPU / "btrc_gpu_surface.c").read_text()
    assert "WGPUSType_SurfaceSourceWindowsHWND" in surface
    assert "glfwGetWin32Window(window)" in surface
    assert "WGPUSType_SurfaceSourceXlibWindow" in surface
    assert "WGPUSType_SurfaceSourceWaylandSurface" in surface
    assert "glfwGetWaylandDisplay()" in surface
    assert "glfwGetWaylandWindow(window)" in surface
    assert "platform == GLFW_PLATFORM_WAYLAND" in surface
    assert "#error" not in surface


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
@pytest.mark.parametrize(
    ("backend", "backend_flags"),
    [("conforming", []), ("wgpu-native", ["-DBTRC_GPU_WGPU_NATIVE"])],
)
def test_gpu_runtime_core_compiles_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    backend: str,
    backend_flags: list[str],
) -> None:
    cflags = os.environ.get("GPU_CFLAGS")
    if not cflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    for source in RUNTIME_SOURCES:
        _compile_strict_c11(
            c_compiler,
            tmp_path / f"{Path(source).stem}-{backend}-{c_compiler}.o",
            [GPU / source],
            [
                *shlex.split(cflags),
                *backend_flags,
                f"-I{GPU}",
                "-O2",
                "-c",
            ],
        )


@pytest.mark.parametrize(
    ("backend", "backend_flags"),
    [("conforming", []), ("wgpu-native", ["-DBTRC_GPU_WGPU_NATIVE"])],
)
def test_gpu_runtime_cross_compiles_for_windows(tmp_path: Path, backend: str, backend_flags: list[str]) -> None:
    cflags = os.environ.get("GPU_CFLAGS")
    zig = shutil.which("zig")
    if not cflags or not zig:
        pytest.skip("Zig or WebGPU/GLFW build flags are unavailable")
    for source in RUNTIME_SOURCES:
        _compile_strict_c11(
            zig,
            tmp_path / f"{Path(source).stem}-{backend}-windows.o",
            [GPU / source],
            [
                "cc",
                "-target",
                "x86_64-windows-gnu",
                *shlex.split(cflags),
                *backend_flags,
                f"-I{GPU}",
                "-c",
            ],
        )
