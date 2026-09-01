import os
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
CONFORMANCE = FIXTURE / "NativeUiAppSession.btrc"
EXPECTED = FIXTURE / "NativeUiAppSession.expected"
COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 90


def _transpile(
    frontend: str,
    output: Path,
    request: pytest.FixtureRequest,
) -> None:
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(output.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(CONFORMANCE),
            "--strict-imports",
            "--no-cache",
            "-o",
            str(output),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        result = subprocess.run(
            [str(btrcc), "--strict-imports", str(CONFORMANCE)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr


def _strict_compile(
    c_compiler: str,
    generated: Path,
    executable: Path,
) -> None:
    flags = [
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        f"-I{FIXTURE}",
        f"-I{APP}",
        f"-I{GPU}",
    ]
    generated_object = executable.with_suffix(".generated.o")
    runtime_object = executable.with_suffix(".runtime.o")
    subprocess.run(
        [c_compiler, *flags, "-c", str(generated), "-o", str(generated_object)],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            c_compiler,
            *flags,
            "-c",
            str(FIXTURE / "fake_app_gpu_runtime.c"),
            "-o",
            str(runtime_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            c_compiler,
            str(generated_object),
            str(runtime_object),
            "-pthread",
            "-o",
            str(executable),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_native_ui_uses_unified_app_gpu_on_both_frontends_and_c_compilers(
    compiler: str,
    c_compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"native-ui-{compiler}-{c_compiler}.c"
    executable = tmp_path / f"native-ui-{compiler}-{c_compiler}"
    _transpile(compiler, generated, request)
    _strict_compile(c_compiler, generated, executable)
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == EXPECTED.read_text()
    assert result.stderr == ""


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_native_ui_cache_multi_evicts_and_recovers_atomically(
    c_compiler: str,
    tmp_path: Path,
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    gpu_flags = shlex.split(os.environ.get("GPU_CFLAGS", ""))
    if not gpu_flags:
        pytest.skip("GPU_CFLAGS is required for the pinned WebGPU headers")
    executable = tmp_path / f"native-ui-cache-{c_compiler}"
    compile_result = subprocess.run(
        [
            c_compiler,
            *gpu_flags,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-DBTRC_GPU_NATIVE_UI_CACHE_TEST",
            "-DBTRC_NATIVE_UI_MAX_IMAGES=3",
            "-DBTRC_NATIVE_UI_MAX_IMAGE_PIXELS=8",
            f"-I{GPU}",
            str(GPU / "btrc_gpu_native_ui.c"),
            str(FIXTURE / "native_ui_cache_smoke.c"),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: native UI cache policy\n"
    assert result.stderr == ""
