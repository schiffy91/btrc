"""Linux provider regressions that watch the provider from underneath: its queue being drained, its controls being placed."""

import subprocess

import pytest

from src.tests.python.linux_provider_fixtures import (
    build_observed_provider_program,
    provider_environment,
)


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(name, marks=pytest.mark.xdist_group(name=f"linux_provider_{name}"))
        for name in ("python", "selfhost")
    ],
)
def frontend(request):
    return request.param


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(False, id="plain", marks=pytest.mark.xdist_group(name="linux_provider_plain")),
        pytest.param(True, id="sanitized", marks=pytest.mark.xdist_group(name="linux_provider_sanitized")),
    ],
)
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
            "eventBoundaryKey",
            "eventBoundaryText",
            "eventBoundaryQueued",
            "eventBoundaryLatest",
            "eventBoundaryFrames",
            "eventBoundaryClose",
            "eventBoundaryDisarm",
            "eventBoundaryAccepted",
            "eventBoundaryRejected",
        ),
        ("btrcGtkPollEvent", "wgpuSurfacePresent", "btrcGtkWindowShowPicture"),
    )


@pytest.fixture(scope="module")
def placement_program(tmp_path_factory, request, frontend, sanitized):
    """The observer counts what the provider hands to GTK and the frames it presents."""
    return build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        "src/tests/native/gui/linux/LinuxPlacement.btrc",
        "src/tests/native/gui/linux/Placement",
        ("placementPlaced", "placementPasses", "placementFrames"),
        ("btrcGtkWindowBeginPlacement", "btrcGtkWindowPlace", "wgpuSurfacePresent", "btrcGtkWindowShowPicture"),
    )


@pytest.mark.parametrize("count", [4095, 4096, 4097, 8193])
@pytest.mark.parametrize("terminal", [0, 1, 2, 3], ids=["keys", "release", "text", "close"])
@pytest.mark.linux_gui
@pytest.mark.xdist_group(name="linux_event_boundary")
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


@pytest.mark.linux_gui
@pytest.mark.xdist_group(name="linux_placement")
def test_linux_controls_are_placed_at_show(placement_program, sanitized, tmp_path):
    """A window's controls are handed to GTK when it is shown, before the GPU
    device is ready and before any frame; a control that leaves the tree leaves the window."""
    result = subprocess.run(
        [str(placement_program)],
        capture_output=True,
        text=True,
        timeout=45,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Linux placement at_show=2 frames_at_show=0 after_detach=1" in result.stdout, result.stdout
