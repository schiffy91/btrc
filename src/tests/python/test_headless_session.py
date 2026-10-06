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
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SESSION = ROOT / "tools/ui/headless-session.sh"
VIRTUAL_DISPLAY = ROOT / "tools/virtual-display.sh"
EVIDENCE = ROOT / "tools/ui/session_evidence.py"
WATCHER = ROOT / "tools/ui/status_notifier_watcher.py"
TIMEOUT = 120
# Run inside the session: what the command sees and what the gates conclude.
PROBE = """
import json, os
from pathlib import Path
from src.tests.runner_capabilities import linux_atspi_error, linux_display_error, linux_wayland_display_error
variables = ("DISPLAY", "WAYLAND_DISPLAY", "SDL_VIDEODRIVER", "GDK_BACKEND", "VK_DRIVER_FILES", "XDG_RUNTIME_DIR")
wayland = os.environ.get("WAYLAND_DISPLAY")
display = os.environ.get("DISPLAY")
if wayland:
    socket = Path(os.environ["XDG_RUNTIME_DIR"], wayland)
else:
    socket = Path("/tmp/.X11-unix", "X" + display.lstrip(":"))
print(json.dumps({
    "environ": {name: os.environ.get(name) for name in variables},
    "display": linux_display_error(),
    "wayland": linux_wayland_display_error(),
    "atspi": linux_atspi_error(),
    "socket": str(socket),
    "inode": socket.stat().st_ino,
}))
"""
# Run inside the session: report the runtime directory, then wait to be stopped.
WAITER = 'printf "%s" "$XDG_RUNTIME_DIR" > "$1.tmp" && mv "$1.tmp" "$1" && exec sleep 60'


def _require_session_tools(*tools: str) -> None:
    if sys.platform != "linux":
        pytest.skip("headless GUI sessions are Linux-only")
    missing = [tool for tool in ("dbus-daemon", *tools) if shutil.which(tool) is None]
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


def _stopped(socket: str, inode: int) -> bool:
    """Whether the server that owned `socket` is gone; under xdist another
    session's Xvfb may already listen on the freed display number."""
    try:
        return Path(socket).stat().st_ino != inode
    except FileNotFoundError:
        return True


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
    # The session stopped Xvfb and removed its private runtime directory.
    assert _stopped(seen["socket"], seen["inode"])
    assert not Path(seen["environ"]["XDG_RUNTIME_DIR"]).exists()


def test_wayland_session_offers_a_compositor_and_the_accessibility_bus():
    _require_session_tools("weston")
    seen = _probe(str(SESSION), "--wayland", "--")
    assert seen["display"] is None
    assert seen["wayland"] is None
    assert seen["atspi"] is None
    assert seen["environ"]["DISPLAY"] is None
    assert seen["environ"]["WAYLAND_DISPLAY"]
    assert (seen["environ"]["SDL_VIDEODRIVER"], seen["environ"]["GDK_BACKEND"]) == ("wayland", "wayland")
    # The session stopped weston and removed its private runtime directory.
    assert _stopped(seen["socket"], seen["inode"])
    assert not Path(seen["environ"]["XDG_RUNTIME_DIR"]).exists()


def test_sessions_never_share_a_runtime_directory(tmp_path):
    """The AT-SPI bus always binds <runtime>/at-spi/bus: a session that reused
    its caller's directory would replace and then delete the caller's socket."""
    _require_session_tools("Xvfb")
    shared = tmp_path / "runtime"
    shared.mkdir(mode=0o700)
    seen = _probe(str(SESSION), "--x11", "--", XDG_RUNTIME_DIR=str(shared))
    assert seen["environ"]["XDG_RUNTIME_DIR"] != str(shared)
    assert not (shared / "at-spi").exists()


@pytest.mark.parametrize(("session", "server"), [(None, "Xvfb"), ("x11", "Xvfb"), ("wayland", "weston")])
def test_virtual_display_delegates_to_the_session(session, server):
    """CI sets nothing and gets X11; BTRC_VIRTUAL_DISPLAY=wayland selects weston."""
    _require_session_tools(server)
    seen = _probe(str(VIRTUAL_DISPLAY), **({"BTRC_VIRTUAL_DISPLAY": session} if session else {}))
    assert seen["display"] is None
    assert seen["atspi"] is None
    assert seen["environ"]["GDK_BACKEND"] == (session or "x11")


def test_virtual_display_adds_no_bash_env_level(tmp_path):
    """The devcontainer re-reads the dev shell through BASH_ENV in every new bash,
    and each read nests another directory into TMPDIR. virtual-display.sh runs the
    session in its own process, so the command sees one level, not two: CI's
    unix-socket fixtures under TMPDIR sit close to sun_path's 108 bytes."""
    _require_session_tools("Xvfb")
    profile = tmp_path / "profile.sh"
    profile.write_text('export TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/level.XXXXXX")"\n')
    root = tmp_path / "tmp"
    root.mkdir()
    result = subprocess.run(
        [str(VIRTUAL_DISPLAY), sys.executable, "-c", "import os; print(os.environ['TMPDIR'])"],
        cwd=ROOT,
        env=_session_environment(BASH_ENV=str(profile), TMPDIR=str(root)),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).parent == root


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


@pytest.mark.parametrize("mode", ["--x11", "--wayland"])
def test_terminating_the_session_stops_the_command_and_the_servers(tmp_path, mode):
    """A TERM to the PID the caller holds, as subprocess timeouts send, reaches the
    session: the command is stopped and everything the session started with it."""
    _require_session_tools("Xvfb" if mode == "--x11" else "weston")
    report = tmp_path / "runtime"
    session = subprocess.Popen(
        [str(SESSION), mode, "--", "sh", "-c", WAITER, "sh", str(report)],
        cwd=ROOT,
        env=_session_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + TIMEOUT
        while not report.exists():
            assert session.poll() is None, session.stderr.read() if session.stderr else ""
            assert time.monotonic() < deadline, "the session never started its command"
            time.sleep(0.1)
        session.terminate()
        assert session.wait(timeout=TIMEOUT) == 143
    finally:
        if session.poll() is None:
            session.kill()
            session.wait(timeout=TIMEOUT)
    assert not Path(report.read_text()).exists()


@pytest.mark.parametrize("mode", ["--x11", "--wayland"])
def test_session_evidence_dumps_the_accessibility_tree_and_keeps_the_status(tmp_path, mode):
    """The GUI shard's wrapper: it samples the session's AT-SPI desktop while the
    command runs and once after, and exits with the command's status."""
    _require_session_tools("Xvfb" if mode == "--x11" else "weston")
    result = subprocess.run(
        [str(SESSION), mode, "--", sys.executable, str(EVIDENCE), "--output", str(tmp_path), "--interval", "0.2"]
        + ["--", "sh", "-c", "sleep 1; exit 5"],
        cwd=ROOT,
        env=_session_environment(),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 5, result.stderr
    dump = json.loads((tmp_path / "atspi.json").read_text())
    assert dump["schema"] == "btrc.atspi-session/1"
    assert dump["session"] == mode.removeprefix("--")
    assert dump["returncode"] == 5
    assert len(dump["samples"]) >= 2
    assert dump["final"]["status"] == "observed", dump["final"]
    assert dump["final"]["desktop"]["role"] == "desktop frame"
    assert all(sample["status"] == "observed" for sample in dump["samples"]), dump["samples"]


def test_session_evidence_records_why_it_cannot_read_a_tree(tmp_path):
    """Without a session bus the dump says why, and the command still decides the status."""
    environment = _session_environment()
    result = subprocess.run(
        [sys.executable, str(EVIDENCE), "--output", str(tmp_path), "--", sys.executable, "-c", "raise SystemExit(3)"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 3, result.stderr
    final = json.loads((tmp_path / "atspi.json").read_text())["final"]
    assert final["status"] == "unavailable"
    assert "session bus" in final["reason"] or "typelibs" in final["reason"]


def test_session_evidence_passes_term_to_the_command(tmp_path):
    if sys.platform != "linux":
        pytest.skip("headless GUI sessions are Linux-only")
    report = tmp_path / "started"
    wrapper = subprocess.Popen(
        [sys.executable, str(EVIDENCE), "--output", str(tmp_path), "--", "sh", "-c", WAITER, "sh", str(report)],
        cwd=ROOT,
        env=_session_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + TIMEOUT
        while not report.exists():
            assert wrapper.poll() is None, wrapper.stderr.read() if wrapper.stderr else ""
            assert time.monotonic() < deadline, "the wrapper never started its command"
            time.sleep(0.1)
        wrapper.terminate()
        assert wrapper.wait(timeout=TIMEOUT) == 143
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=TIMEOUT)
    assert json.loads((tmp_path / "atspi.json").read_text())["returncode"] == -15


@pytest.mark.parametrize("mode", ["--x11", "--wayland"])
def test_stand_in_watcher_gives_the_tray_provider_a_watcher(mode):
    """The GUI shard runs the Linux tray tests on this watcher instead of skipping them."""
    _require_session_tools("Xvfb" if mode == "--x11" else "weston")
    probe = (
        "import sys\n"
        "from src.tests.runner_capabilities import linux_tray_backend_error\n"
        "print(linux_tray_backend_error())\n"
        "sys.exit(4)\n"
    )
    result = subprocess.run(
        [str(SESSION), mode, "--", sys.executable, str(WATCHER), "--", sys.executable, "-c", probe],
        cwd=ROOT,
        env=_session_environment(),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 4, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "None", result.stdout


def test_terminating_the_session_stops_the_command_under_the_watcher(tmp_path):
    _require_session_tools("Xvfb")
    report = tmp_path / "runtime"
    session = subprocess.Popen(
        [str(SESSION), "--x11", "--", sys.executable, str(WATCHER), "--", "sh", "-c", WAITER, "sh", str(report)],
        cwd=ROOT,
        env=_session_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + TIMEOUT
        while not report.exists():
            assert session.poll() is None, session.stderr.read() if session.stderr else ""
            assert time.monotonic() < deadline, "the watcher never started its command"
            time.sleep(0.1)
        session.terminate()
        assert session.wait(timeout=TIMEOUT) == 143
    finally:
        if session.poll() is None:
            session.kill()
            session.wait(timeout=TIMEOUT)
    assert not Path(report.read_text()).exists()


def test_stand_in_watcher_reports_a_command_it_cannot_start():
    _require_session_tools("Xvfb")
    result = subprocess.run(
        [str(SESSION), "--x11", "--", sys.executable, str(WATCHER), "--", "/nonexistent/btrc-command"],
        cwd=ROOT,
        env=_session_environment(),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 127, result.stderr
    assert "cannot start /nonexistent/btrc-command" in result.stderr


def test_stand_in_watcher_never_runs_its_command_without_a_bus(tmp_path):
    marker = tmp_path / "ran"
    result = subprocess.run(
        [sys.executable, str(WATCHER), "--", sys.executable, "-c", f"open({str(marker)!r}, 'w')"],
        cwd=ROOT,
        env=_session_environment(
            DBUS_SESSION_BUS_ADDRESS=f"unix:path={tmp_path / 'missing'}", XDG_RUNTIME_DIR=str(tmp_path)
        ),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 2, result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("arguments", [[], ["--x11"], ["--x11", "--"], ["--x11", "--wayland", "--", "true"], ["--vnc"]])
def test_session_rejects_a_malformed_invocation(arguments):
    result = subprocess.run([str(SESSION), *arguments], cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT)
    assert result.returncode == 2
    assert "usage:" in result.stderr
