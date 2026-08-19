import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GPU = ROOT / "src" / "stdlib" / "gpu"
ASYNC_FIXTURE = ROOT / "src" / "tests" / "native" / "gpu_async"
PENDING_HARNESS = ROOT / "src" / "tests" / "native" / "gpu_pending_list.c"
RUNTIME_SOURCES = ["btrc_gpu.c", "btrc_gpu_async.c", "btrc_gpu_surface.c"]
_COMPILE_TIMEOUT_SECONDS = 120
_RUN_TIMEOUT_SECONDS = 90
_TSAN_PROBE = """\
#include <pthread.h>

static void *run(void *unused) {
    return unused;
}

int main(void) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, run, NULL) != 0) return 1;
    return pthread_join(thread, NULL) == 0 ? 0 : 2;
}
"""


def _compile_strict_c11(compiler: str, output: Path, sources: list[Path], flags: list[str]) -> None:
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
    command = [compiler, *flags, *strict, *map(str, sources), "-o", str(output)]
    subprocess.run(command, check=True, timeout=_COMPILE_TIMEOUT_SECONDS)


def _tsan_compile_flags(flags: list[str]) -> list[str]:
    return [
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-O1",
        "-g",
        "-fsanitize=thread",
        "-fno-omit-frame-pointer",
        "-pthread",
        f"-I{GPU}",
        *flags,
    ]


def _compile_tsan(compiler: str, output: Path, sources: list[Path], flags: list[str]):
    return subprocess.run(
        [compiler, *_tsan_compile_flags(flags), *map(str, sources), "-o", str(output)],
        capture_output=True,
        text=True,
        timeout=_COMPILE_TIMEOUT_SECONDS,
    )


def _run_tsan(executable: Path):
    return subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        env={**os.environ, "TSAN_OPTIONS": "halt_on_error=1"},
        timeout=_RUN_TIMEOUT_SECONDS,
    )


def _compile_tsan_probe(tmp_path: Path, compiler: str, flags: list[str]) -> Path:
    source = tmp_path / "tsan-runtime-probe.c"
    executable = tmp_path / "tsan-runtime-probe"
    source.write_text(_TSAN_PROBE, encoding="utf-8")
    compiled = _compile_tsan(compiler, executable, [source], flags)
    if compiled.returncode != 0:
        pytest.skip(f"ThreadSanitizer is unavailable: {compiled.stderr}")
    return executable


def _probe_darwin_tsan_runtime(executable: Path) -> None:
    result = _run_tsan(executable)
    silent_signal = result.returncode < 0 and not result.stdout and not result.stderr
    if silent_signal:
        pytest.skip("ThreadSanitizer runtime crashes on an independent exact-flags probe")
    assert result.returncode == 0, result.stderr or result.stdout


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
    completion = async_runtime.split("void btrc_gpu_async_complete", 1)[1]
    assert completion.index("async->status = status") < completion.index("memory_order_release")
    assert "memory_order_acquire) == BTRC_GPU_ASYNC_DONE" in async_runtime
    assert ".userdata2 = NULL" in runtime
    assert "gpu_async_cancel_drain_timeout_ns" in runtime
    assert "static void reap_pending_async(GPU_* gpu)" in runtime
    assert "pending->future = map_future" in runtime
    readback = runtime.split("bool btrc_gpu_read_buffer_checked", 1)[1]
    timeout_cleanup = readback.split("if (outcome != BTRC_GPU_ASYNC_COMPLETED)", 1)[1].split("bool success", 1)[0]
    assert timeout_cleanup.index("wgpuBufferRelease(staging)") < timeout_cleanup.index("pending->future = map_future")


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


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_gpu_pending_list_concurrent_detach_and_merge(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"gpu-pending-list-{c_compiler}"
    _compile_strict_c11(
        c_compiler,
        executable,
        [PENDING_HARNESS],
        [f"-I{GPU}", "-pthread"],
    )
    subprocess.run([str(executable)], check=True, timeout=_RUN_TIMEOUT_SECONDS)


@pytest.mark.parametrize(
    ("name", "sources", "flags"),
    [
        ("pending-list", [PENDING_HARNESS], []),
        (
            "async-publication",
            [
                ASYNC_FIXTURE / "gpu_async_state_machine.c",
                ASYNC_FIXTURE / "fake_webgpu_runtime.c",
                GPU / "btrc_gpu_async.c",
            ],
            [f"-I{ASYNC_FIXTURE}"],
        ),
    ],
)
def test_gpu_concurrency_contracts_under_thread_sanitizer(
    tmp_path: Path,
    name: str,
    sources: list[Path],
    flags: list[str],
) -> None:
    compiler_name = "clang" if sys.platform == "darwin" else "gcc"
    compiler = shutil.which(compiler_name)
    if not compiler:
        pytest.skip(f"{compiler_name} ThreadSanitizer is unavailable")
    probe = _compile_tsan_probe(tmp_path, compiler, flags)
    executable = tmp_path / f"gpu-{name}-tsan"
    compile_result = _compile_tsan(compiler, executable, sources, flags)
    assert compile_result.returncode == 0, compile_result.stderr
    if sys.platform == "darwin":
        _probe_darwin_tsan_runtime(probe)
    result = _run_tsan(executable)
    unavailable = "unexpected memory mapping" in result.stderr
    if result.returncode != 0 and unavailable:
        pytest.skip(f"ThreadSanitizer runtime is unavailable: {result.stderr}")
    failure = result.stderr or result.stdout
    if result.returncode < 0 and not failure:
        failure = f"GPU ThreadSanitizer harness terminated by signal {-result.returncode}"
    assert result.returncode == 0, failure


def test_gpu_archive_rule_asserts_runtime_membership() -> None:
    makefile = (ROOT / "Makefile").read_text()
    runtime = (GPU / "btrc_gpu.c").read_text()
    assert "GPU_BACKEND_CFLAGS ?= -DBTRC_GPU_WGPU_NATIVE" in makefile
    assert "GPU_THREAD_FLAGS ?= $(if $(filter Windows_NT,$(OS)),,-pthread)" in makefile
    assert "$(GPU_BACKEND_CFLAGS) $(GPU_THREAD_FLAGS) $(NATIVE_CFLAGS)" in makefile
    assert "pthreads on POSIX hosts" in runtime
    archive_cleanup = makefile.index('rm -f "$$O/libbtrc_gpu.a"')
    dependency_probe = makefile.index("for source in btrc_gpu.c btrc_gpu_async.c btrc_gpu_surface.c")
    assert archive_cleanup < dependency_probe
    assert '-E "$$D/$$source" -o /dev/null' in makefile
    assert '-E "$$D/btrc_gpu_surface_macos.m" -o /dev/null' in makefile
    assert "btrc_gpu_async.o $$O/btrc_gpu_surface.o" in makefile
    assert r'grep -q "btrc_gpu_async\\.o$$"' in makefile
    assert r'grep -q "btrc_gpu_surface\\.o$$"' in makefile


@pytest.mark.parametrize("example", ["game", "triangle", "sgd"])
def test_gpu_example_link_commands_include_platform_thread_flags(example: str) -> None:
    makefile = (ROOT / "examples" / example / "Makefile").read_text()
    assert "GPU_THREAD_FLAGS ?= $(if $(filter Windows_NT,$(OS)),,-pthread)" in makefile
    link_flags = next(line for line in makefile.splitlines() if line.startswith("LDFLAGS"))
    assert "$(GPU_THREAD_FLAGS)" in link_flags


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
