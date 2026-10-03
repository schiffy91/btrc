"""tools/ui/headless-session.sh: a private X11 or Wayland display inside its own
session bus, with the AT-SPI accessibility bus, torn down with the command.

Each case starts a real session and asks the capability gates in
runner_capabilities.py what they see from inside it, so the gates and the
script prove each other. The dev shell provides every tool (flake.nix); the
devcontainer image is built from that shell, so there a missing tool is a
broken image, not an absent capability."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SESSION = ROOT / "tools/ui/headless-session.sh"
VIRTUAL_DISPLAY = ROOT / "tools/virtual-display.sh"
TIMEOUT = 120
# Run inside the session: what the command sees and what the gates conclude.
PROBE = """
import json, os, sys
from pathlib import Path
from src.tests.runner_capabilities import linux_atspi_error, linux_display_error, linux_wayland_display_error
variables = ("DISPLAY", "WAYLAND_DISPLAY", "SDL_VIDEODRIVER", "GDK_BACKEND", "VK_DRIVER_FILES", "XDG_RUNTIME_DIR")
wayland = os.environ.get("WAYLAND_DISPLAY")
display = os.environ.get("DISPLAY")
print(json.dumps({
    "environ": {name: os.environ.get(name) for name in variables},
    "display": linux_display_error(),
    "wayland": linux_wayland_display_error(),
    "atspi": linux_atspi_error(),
    "socket": str(Path(os.environ["XDG_RUNTIME_DIR"], wayland)) if wayland
    else f"/tmp/.X11-unix/X{display.lstrip(':')}" if display else None,
}))
"""


def _require_session_tools(*tools: str) -> None:
    if sys.platform != "linux":
        pytest.skip("headless GUI sessions are Linux-only")
    missing = [tool for tool in ("dbus-run-session", *tools) if shutil.which(tool) is None]
    missing += [] if os.environ.get("BTRC_ATSPI_LIBEXEC") else ["BTRC_ATSPI_LIBEXEC"]
    if not missing:
        return
    error = f"the headless session needs the dev shell's {', '.join(missing)}"
    if os.environ.get("DEVCONTAINER") == "true":
        pytest.fail(f"the devcontainer image is built from the dev shell; run make devcontainer: {error}")
    pytest.skip(error)


def _session_environment(**overrides: str) -> dict[str, str]:
    """The caller's environment without a display or bus, as on a CI runner."""
    environment = dict(os.environ)
    for name in (
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
        "SDL_VIDEODRIVER",
        "GDK_BACKEND",
        "BTRC_VIRTUAL_DISPLAY",
    ):
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(ROOT)
    return {**environment, **overrides}


def _probe(*command: str, **overrides: str) -> dict:
    result = subprocess.run(
        [*command, sys.executable, "-c", PROBE],
        cwd=ROOT,
        env=_session_environment(**overrides),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_x11_session_offers_a_display_and_the_accessibility_bus():
    _require_session_tools("Xvfb")
    seen = _probe(str(SESSION), "--x11", "--")
    assert seen["display"] is None
    assert seen["atspi"] is None
    assert seen["wayland"] == "native Wayland backend is unavailable: no WAYLAND_DISPLAY"
    assert seen["environ"]["DISPLAY"].startswith(":")
    assert seen["environ"]["WAYLAND_DISPLAY"] is None
    assert (seen["environ"]["SDL_VIDEODRIVER"], seen["environ"]["GDK_BACKEND"]) == ("x11", "x11")
    if os.environ.get("BTRC_LAVAPIPE_ICD"):
        assert seen["environ"]["VK_DRIVER_FILES"] == os.environ["BTRC_LAVAPIPE_ICD"]
    # Xvfb removed its socket when the session stopped it.
    assert not Path(seen["socket"]).exists()


def test_wayland_session_offers_a_compositor_and_the_accessibility_bus():
    _require_session_tools("weston")
    seen = _probe(str(SESSION), "--wayland", "--")
    assert seen["display"] is None
    assert seen["wayland"] is None
    assert seen["atspi"] is None
    assert seen["environ"]["DISPLAY"] is None
    assert seen["environ"]["WAYLAND_DISPLAY"]
    assert (seen["environ"]["SDL_VIDEODRIVER"], seen["environ"]["GDK_BACKEND"]) == ("wayland", "wayland")
    # weston removed its socket, and the session its private runtime directory.
    assert not Path(seen["socket"]).exists()
    if not os.environ.get("XDG_RUNTIME_DIR"):
        assert not Path(seen["environ"]["XDG_RUNTIME_DIR"]).exists()


@pytest.mark.parametrize(("session", "server"), [(None, "Xvfb"), ("x11", "Xvfb"), ("wayland", "weston")])
def test_virtual_display_delegates_to_the_session(session, server):
    """CI sets nothing and gets X11; BTRC_VIRTUAL_DISPLAY=wayland selects weston."""
    _require_session_tools(server)
    seen = _probe(str(VIRTUAL_DISPLAY), **({"BTRC_VIRTUAL_DISPLAY": session} if session else {}))
    assert seen["display"] is None
    assert seen["atspi"] is None
    assert seen["environ"]["GDK_BACKEND"] == (session or "x11")


def test_virtual_display_rejects_an_unknown_session():
    if sys.platform != "linux":
        pytest.skip("headless GUI sessions are Linux-only")
    result = subprocess.run(
        [str(VIRTUAL_DISPLAY), "true"],
        cwd=ROOT,
        env=_session_environment(BTRC_VIRTUAL_DISPLAY="vnc"),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 2
    assert "BTRC_VIRTUAL_DISPLAY must be x11 or wayland" in result.stderr


@pytest.mark.parametrize("mode", ["--x11", "--wayland"])
def test_session_returns_the_command_status(mode):
    _require_session_tools("Xvfb" if mode == "--x11" else "weston")
    result = subprocess.run(
        [str(SESSION), mode, "--", "sh", "-c", "exit 7"],
        cwd=ROOT,
        env=_session_environment(),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 7, result.stderr


@pytest.mark.parametrize("arguments", [[], ["--x11"], ["--x11", "--"], ["--x11", "--wayland", "--", "true"], ["--vnc"]])
def test_session_rejects_a_malformed_invocation(arguments):
    result = subprocess.run([str(SESSION), *arguments], cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT)
    assert result.returncode == 2
    assert "usage:" in result.stderr
