import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src" / "stdlib" / "app"
GPU = ROOT / "src" / "stdlib" / "gpu"
FIXTURE = ROOT / "src" / "tests" / "native" / "app_surface"
HARNESS = FIXTURE / "gpu_attach_actual_runtime.c"
GPU_REDIRECT = FIXTURE / "gpu_attach_test_redirect.h"
ASYNC_REDIRECT = FIXTURE / "gpu_attach_async_test_redirect.h"
INTEGRATED_HARNESS = FIXTURE / "integrated_app_gpu_runtime.c"
INTEGRATED_GPU_REDIRECT = FIXTURE / "integrated_gpu_test_redirect.h"
INTEGRATED_ASYNC_REDIRECT = FIXTURE / "integrated_gpu_async_test_redirect.h"
FAKE_GLFW = FIXTURE / "fake_glfw"
COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 90


def _sanitizer_flags() -> list[str]:
    # macOS 26's ASan runtime deadlocks before main; UBSan remains runnable.
    macos_major = platform.mac_ver()[0].split(".", 1)[0]
    asan_deadlocks = sys.platform == "darwin" and macos_major.isdigit() and int(macos_major) >= 26
    sanitizer = "undefined" if asan_deadlocks else "address,undefined"
    return [
        "-O1",
        "-g",
        "-fno-omit-frame-pointer",
        f"-fsanitize={sanitizer}",
    ]


def _compile_actual_runtime(
    compiler: str,
    output: Path,
    extra_flags: list[str] | None = None,
) -> None:
    cflags = os.environ.get("GPU_CFLAGS")
    ldflags = os.environ.get("GPU_LDFLAGS")
    if not cflags or not ldflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")

    strict = [
        compiler,
        *shlex.split(cflags),
        "-DBTRC_GPU_WGPU_NATIVE",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        *(extra_flags or []),
        f"-I{APP}",
        f"-I{GPU}",
        f"-I{FIXTURE}",
    ]
    gpu_object = output.with_suffix(".gpu.o")
    native_ui_object = output.with_suffix(".native-ui.o")
    async_object = output.with_suffix(".async.o")
    harness_object = output.with_suffix(".harness.o")
    subprocess.run(
        [
            *strict,
            "-include",
            str(GPU_REDIRECT),
            "-c",
            str(GPU / "btrc_gpu.c"),
            "-o",
            str(gpu_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-c",
            str(GPU / "btrc_gpu_native_ui.c"),
            "-o",
            str(native_ui_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-include",
            str(ASYNC_REDIRECT),
            "-c",
            str(GPU / "btrc_gpu_async.c"),
            "-o",
            str(async_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-c",
            str(HARNESS),
            "-o",
            str(harness_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            compiler,
            *(extra_flags or []),
            str(gpu_object),
            str(native_ui_object),
            str(async_object),
            str(harness_object),
            *shlex.split(ldflags),
            "-lm",
            "-pthread",
            "-o",
            str(output),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )


def _compile_integrated_runtime(
    compiler: str,
    output: Path,
    extra_flags: list[str] | None = None,
) -> None:
    cflags = os.environ.get("GPU_CFLAGS")
    ldflags = os.environ.get("GPU_LDFLAGS")
    if not cflags or not ldflags:
        pytest.skip("WebGPU/GLFW build flags are unavailable")

    strict = [
        compiler,
        *shlex.split(cflags),
        "-DBTRC_GPU_WGPU_NATIVE",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        *(extra_flags or []),
        f"-I{FAKE_GLFW}",
        f"-I{APP}",
        f"-I{GPU}",
        f"-I{FIXTURE}",
    ]
    app_object = output.with_suffix(".app.o")
    gpu_object = output.with_suffix(".gpu.o")
    native_ui_object = output.with_suffix(".native-ui.o")
    async_object = output.with_suffix(".async.o")
    fake_glfw_object = output.with_suffix(".fake-glfw.o")
    harness_object = output.with_suffix(".harness.o")
    subprocess.run(
        [
            *strict,
            "-Dcalloc=btrc_app_test_calloc",
            "-Dfree=btrc_app_test_free",
            "-c",
            str(APP / "btrc_app.c"),
            "-o",
            str(app_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-include",
            str(INTEGRATED_GPU_REDIRECT),
            "-c",
            str(GPU / "btrc_gpu.c"),
            "-o",
            str(gpu_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-c",
            str(GPU / "btrc_gpu_native_ui.c"),
            "-o",
            str(native_ui_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-include",
            str(INTEGRATED_ASYNC_REDIRECT),
            "-c",
            str(GPU / "btrc_gpu_async.c"),
            "-o",
            str(async_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    for source, object_file in [
        (FIXTURE / "fake_glfw_runtime.c", fake_glfw_object),
        (INTEGRATED_HARNESS, harness_object),
    ]:
        subprocess.run(
            [*strict, "-c", str(source), "-o", str(object_file)],
            check=True,
            timeout=COMPILE_TIMEOUT,
        )
    subprocess.run(
        [
            compiler,
            *(extra_flags or []),
            str(app_object),
            str(gpu_object),
            str(native_ui_object),
            str(async_object),
            str(fake_glfw_object),
            str(harness_object),
            *shlex.split(ldflags),
            "-lm",
            "-pthread",
            "-o",
            str(output),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_actual_gpu_attachment_partial_initialization_and_cleanup(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    compiler = shutil.which(c_compiler)
    if not compiler:
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"gpu-attachment-{c_compiler}"
    _compile_actual_runtime(compiler, executable)
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: actual GPU attachment lifecycle\n"


def test_actual_gpu_attachment_under_clang_sanitizers(tmp_path: Path) -> None:
    compiler = "/usr/bin/clang" if sys.platform == "darwin" else shutil.which("clang")
    if not compiler or not Path(compiler).is_file():
        pytest.skip("clang is unavailable")
    executable = tmp_path / "gpu-attachment-sanitized"
    _compile_actual_runtime(
        compiler,
        executable,
        _sanitizer_flags(),
    )
    result = subprocess.run(
        [str(executable)],
        env={
            **os.environ,
            "ASAN_OPTIONS": "halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1",
        },
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: actual GPU attachment lifecycle\n"


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_integrated_production_app_gpu_finalizer_graph(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    compiler = shutil.which(c_compiler)
    if not compiler:
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"integrated-app-gpu-{c_compiler}"
    _compile_integrated_runtime(compiler, executable)
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("PASS: integrated production app/GPU finalizer graph\n")


def test_integrated_production_app_gpu_finalizer_graph_under_clang_sanitizers(
    tmp_path: Path,
) -> None:
    compiler = "/usr/bin/clang" if sys.platform == "darwin" else shutil.which("clang")
    if not compiler or not Path(compiler).is_file():
        pytest.skip("clang is unavailable")
    executable = tmp_path / "integrated-app-gpu-sanitized"
    _compile_integrated_runtime(
        compiler,
        executable,
        _sanitizer_flags(),
    )
    result = subprocess.run(
        [str(executable)],
        env={
            **os.environ,
            "ASAN_OPTIONS": "halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1",
        },
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("PASS: integrated production app/GPU finalizer graph\n")
