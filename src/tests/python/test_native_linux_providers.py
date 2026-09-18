"""The Linux stdlib providers on real SDKs: the drawn GUI over SDL3 and
WebGPU, libpng/libjpeg-turbo decoding, and ALSA duplex sessions.

Each program compiles through both frontends against the Linux target, links
through the native plan, and runs optimized and under ASan/UBSan. Display and
audio cases skip where the session offers neither."""

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.runner_capabilities import linux_audio_backend_error, linux_display_error
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
TARGET = "linux-x86_64" if platform.machine() in ("x86_64", "AMD64") else "linux-aarch64"


def _require_linux_reader():
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")


def _transpile(source: Path, generated: Path, plan: Path, frontend: str, request) -> None:
    environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            TARGET,
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ]
    else:
        command = [
            str(request.getfixturevalue("immutable_btrcc")),
            "--target",
            TARGET,
            "--emit-link-plan",
            str(plan),
            str(source),
        ]
    compiled = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=600)
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout)


def _build_and_run(
    source: Path, tmp_path: Path, frontend: str, sanitized: bool, request, expected: str, timeout: int = 120
) -> None:
    generated = tmp_path / "Program.c"
    plan = tmp_path / "Program.json"
    _transpile(source, generated, plan, frontend, request)
    executable = tmp_path / "Program"

    def run(command, **kwargs):
        if sanitized and "-o" in command:
            command = [*command, "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    environment = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    # libasan intercepts dlopen, so wgpu-native's own runpath no longer reaches
    # the Vulkan loader; NixOS keeps it under the driver prefix.
    driver = Path("/run/opengl-driver/lib")
    if sanitized and driver.is_dir():
        environment["LD_LIBRARY_PATH"] = ":".join(filter(None, [os.environ.get("LD_LIBRARY_PATH"), str(driver)]))
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=timeout, env=environment)
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_image_decoding(tmp_path, request, frontend, sanitized):
    _require_linux_reader()
    _build_and_run(
        ROOT / "src/tests/native/image/linux/LinuxImageDecoding.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux image decoding",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_audio_session(tmp_path, request, frontend, sanitized):
    _require_linux_reader()
    if error := linux_audio_backend_error():
        pytest.skip(error)
    _build_and_run(
        ROOT / "src/tests/native/audio/linux/LinuxAudioSession.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux audio session",
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_gui_controls(tmp_path, request, frontend, sanitized):
    """A live window: synthetic input drives every control kind and the composed frame reads back."""
    _require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    _build_and_run(
        ROOT / "src/tests/native/gui/linux/LinuxGUIControls.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        "PASS: linux gui controls",
        timeout=180,
    )


@pytest.mark.parametrize("target", ["windows-x86_64"])
def test_linux_gui_unsupported_target(target, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            target,
            str(ROOT / "src/tests/native/gui/linux/LinuxGUIControls.btrc"),
            "-o",
            str(tmp_path / "Program.c"),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "provider" in result.stderr.lower()
