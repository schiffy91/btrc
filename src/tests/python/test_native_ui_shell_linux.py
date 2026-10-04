"""Real SDL shell rows; invoke inside headless-session.sh --x11 or --wayland."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.linux_provider_fixtures import transpile_provider_program
from src.tests.python.native_ui_shell_fixtures import exercise_shell
from src.tests.runner_capabilities import linux_display_error
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_native_shell(tmp_path, request, frontend, sanitized):
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    if error := linux_display_error():
        pytest.skip(error)
    provider = "linux-wayland" if os.environ.get("SDL_VIDEODRIVER") == "wayland" else "linux-x11"
    exercise_shell(tmp_path, request, frontend, sanitized, provider)


@pytest.fixture(scope="module", params=["python", "selfhost"])
def event_boundary_program(tmp_path_factory, request, gui_provider_root):
    """D24 reproduction only: a real provider with a precisely isolated SDL queue."""
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    if error := linux_display_error():
        pytest.skip(error)
    NativeBindingPackage.require_reader()
    root = Path(__file__).resolve().parents[3]
    directory = tmp_path_factory.mktemp(f"e40-{request.param}")
    probe = root / "src/tests/native/gui/shell/probes/linux/EventBoundary"
    source = NativeBindingPackage.write(
        root / "src/tests/native/gui/linux/LinuxEventBoundary.btrc",
        directory / "package",
        probe.with_suffix(".h"),
        ("eventBoundaryArm", "eventBoundaryQueued", "eventBoundaryLatest", "eventBoundaryClose", "eventBoundaryDisarm"),
    )
    generated, plan = directory / "Program.c", directory / "Program.json"
    transpile_provider_program(source, generated, plan, request.param, request, data_root=gui_provider_root)
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "sdl3"], text=True, timeout=30).split()
    obj = directory / "EventBoundary.o"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            *flags,
            "-c",
            str(probe.with_suffix(".c")),
            "-o",
            str(obj),
        ],
        check=True,
        timeout=120,
    )

    def run(command, **kwargs):
        command = list(command)
        if "-c" not in command and "-o" in command:
            command.extend([str(obj), "-Wl,--wrap=SDL_PollEvent"])
        kwargs.setdefault("timeout", 120)
        return subprocess.run(command, **kwargs)

    executable = directory / "EventBoundary"
    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    return executable


@pytest.mark.parametrize("count", [4095, 4096, 4097, 8193])
@pytest.mark.parametrize("terminal", [0, 1, 2, 3], ids=["keys", "release", "text", "close"])
def test_linux_event_boundary(event_boundary_program, count, terminal):
    """Lossless delivery is the required behavior: boundary losses fail, never xfail."""
    result = subprocess.run(
        [str(event_boundary_program), str(count), str(terminal)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
