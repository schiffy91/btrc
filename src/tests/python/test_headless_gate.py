"""tools/headless-gate.sh: a gate's environment on a desktop, as the native Linux manifest is qualified."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "headless-gate.sh"
pytestmark = pytest.mark.skipif(os.name != "posix", reason="the script is POSIX shell")


def _run(*command: str, **environment: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *command],
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_gate_cannot_see_the_session_it_is_started_from(tmp_path: Path) -> None:
    session = tmp_path / "session-runtime"
    session.mkdir()
    probe = 'env; printf "mode=%s\\n" "$(stat -c %a "$XDG_RUNTIME_DIR" 2>/dev/null || stat -f %Lp "$XDG_RUNTIME_DIR")"'
    result = _run(
        "sh",
        "-c",
        probe,
        DISPLAY=":0",
        WAYLAND_DISPLAY="wayland-0",
        XDG_RUNTIME_DIR=str(session),
        DBUS_SESSION_BUS_ADDRESS=f"unix:path={session}/bus",
        CPATH="/another/shell/include",
        NIX_CFLAGS_COMPILE="-isystem /another/shell/include",
        BTRC_CC="clang",
    )
    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    for leaked in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "CPATH", "NIX_CFLAGS_COMPILE", "BTRC_CC"):
        assert leaked not in seen, leaked
    runtime = Path(seen["XDG_RUNTIME_DIR"])
    assert runtime != session and seen["mode"] == "700"
    # A Wayland client with no WAYLAND_DISPLAY tries wayland-0 here: the path must fit a socket address.
    assert len(str(runtime / "wayland-0")) < 108
    assert seen["HOME"] == os.environ["HOME"] and seen["PATH"]
    # The directory is the command's alone and is gone with it.
    assert not runtime.exists()


def test_the_commands_status_is_the_scripts_and_a_command_is_required() -> None:
    assert _run("sh", "-c", "exit 7").returncode == 7
    missing = _run()
    assert missing.returncode == 64 and "usage: tools/headless-gate.sh" in missing.stderr
    assert stat.S_IMODE(SCRIPT.stat().st_mode) & stat.S_IXUSR
