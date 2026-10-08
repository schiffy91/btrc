"""Existing Linux provider regressions, using real SDL event dispatch."""

import shlex
import subprocess
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.python.linux_provider_fixtures import (
    provider_environment,
    require_linux_reader,
    transpile_provider_program,
)
from src.tests.runner_capabilities import linux_display_error
from tools.native_plan import NativePlanBuilder


@pytest.fixture(scope="module", params=["python", "selfhost"])
def frontend(request):
    return request.param


@pytest.fixture(scope="module", params=[False, True], ids=["plain", "sanitized"])
def sanitized(request):
    return request.param


@pytest.fixture(scope="module")
def event_boundary_program(tmp_path_factory, request, frontend, sanitized):
    """Only the actual provider dequeues; the native observer delegates every poll."""
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    # Request expensive fixtures only after the platform/reader/display guards.
    data_root = request.getfixturevalue("gui_provider_root")
    root = Path(__file__).resolve().parents[3]
    directory = tmp_path_factory.mktemp(f"e40-{frontend}-{'sanitized' if sanitized else 'plain'}")
    probe = root / "src/tests/native/gui/shell/probes/linux/EventBoundary"
    source = NativeBindingPackage.write(
        root / "src/tests/native/gui/linux/LinuxEventBoundary.btrc",
        directory / "package",
        probe.with_suffix(".h"),
        ("eventBoundaryArm", "eventBoundaryQueued", "eventBoundaryLatest", "eventBoundaryClose", "eventBoundaryDisarm"),
    )
    generated, plan = directory / "Program.c", directory / "Program.json"
    transpile_provider_program(source, generated, plan, frontend, request, data_root=data_root)
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "sdl3"], text=True, timeout=TOOL_TIMEOUT))
    sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    observer = directory / "EventBoundary.o"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            *sanitizers,
            *flags,
            "-c",
            str(probe.with_suffix(".c")),
            "-o",
            str(observer),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )

    def run(command, **kwargs):
        command = list(command)
        if "-c" in command:
            command[1:1] = sanitizers
        elif "-o" in command:
            command.extend([str(observer), "-Wl,--wrap=SDL_PollEvent", *sanitizers])
        kwargs.setdefault("timeout", C_COMPILE_TIMEOUT)
        return subprocess.run(command, **kwargs)

    executable = directory / "EventBoundary"
    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    return executable


@pytest.mark.parametrize("count", [4095, 4096, 4097, 8193])
@pytest.mark.parametrize("terminal", [0, 1, 2, 3], ids=["keys", "release", "text", "close"])
def test_linux_event_boundary(event_boundary_program, sanitized, count, terminal, tmp_path):
    """Lossless, bounded delivery and inter-turn work progress must all hold."""
    environment = provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run(
        [str(event_boundary_program), str(count), str(terminal)],
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bounded=1 work=1 lossless=1" in result.stdout, result.stdout
