"""Existing Linux provider regressions, using real SDL event dispatch."""

import subprocess

import pytest

from src.tests.python.linux_provider_fixtures import (
    build_observed_provider_program,
    provider_environment,
)


@pytest.fixture(scope="module", params=["python", "selfhost"])
def frontend(request):
    return request.param


@pytest.fixture(scope="module", params=[False, True], ids=["plain", "sanitized"])
def sanitized(request):
    return request.param


@pytest.fixture(scope="module")
def event_boundary_program(tmp_path_factory, request, frontend, sanitized):
    """Only the actual provider dequeues; the observer delegates polls/presentation."""
    return build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        "src/tests/native/gui/linux/LinuxEventBoundary.btrc",
        "src/tests/native/gui/shell/probes/linux/EventBoundary",
        (
            "eventBoundaryArm",
            "eventBoundaryQueued",
            "eventBoundaryLatest",
            "eventBoundaryFrames",
            "eventBoundaryClose",
            "eventBoundaryDisarm",
            "eventBoundaryAccepted",
            "eventBoundaryRejected",
        ),
        ("SDL_PollEvent", "SDL_PushEvent", "wgpuSurfacePresent"),
    )


@pytest.fixture(scope="module")
def input_repair_program(tmp_path_factory, request, frontend, sanitized):
    return build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        "src/tests/native/gui/ui2/probes/linux/LinuxInputRepair.btrc",
        "src/tests/native/gui/ui2/probes/linux/InputRepair",
        ("inputFailClipboard", "inputClipboardWrites", "inputClipboardMatches", "inputFrames", "inputVisibility"),
        ("SDL_SetClipboardText", "wgpuSurfacePresent"),
    )


@pytest.mark.parametrize("count", [4095, 4096, 4097, 8193])
@pytest.mark.parametrize("terminal", [0, 1, 2, 3], ids=["keys", "release", "text", "close"])
@pytest.mark.linux_gui
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
    assert "bounded=1 work=1 frame=1 lossless=1" in result.stdout, result.stdout


@pytest.mark.parametrize("mode", [0, 1, 2, 3], ids=["failed-cut", "popup-below", "popup-above", "external-visibility"])
@pytest.mark.linux_gui
def test_linux_input_repair(input_repair_program, sanitized, mode, tmp_path):
    result = subprocess.run(
        [str(input_repair_program), str(mode)],
        capture_output=True,
        text=True,
        timeout=45,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS: Linux input repair {mode}" in result.stdout, result.stdout
