"""Real SDL shell rows; invoke inside headless-session.sh --x11 or --wayland."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.python.native_ui_shell_fixtures import exercise_shell
from src.tests.runner_capabilities import linux_display_error
from tools.qualification.report import LedgerRollup
from tools.qualification.schema import LedgerDocument
from tools.qualification.skips import RunnerIdentity


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.linux_gui
def test_linux_native_shell(tmp_path, request, frontend, sanitized):
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    if error := linux_display_error():
        pytest.skip(error)
    provider = "linux-wayland" if os.environ.get("SDL_VIDEODRIVER") == "wayland" else "linux-x11"
    exercise_shell(tmp_path, request, frontend, sanitized, provider)


# The real-session check (CL-UIA-11 step 3) waits on a physical Linux desktop:
# PLAN D7's x86_64 host, which has no self-hosted runner yet. Hosted and
# container runs skip it with this command, which that host runs in each of its
# X11 and Wayland sessions.
DESKTOP_CHECK = "nix develop --command tools/ui/linux-desktop-check.sh --artifacts <dir> > linux-desktop-check.json"


def test_linux_real_desktop_session(tmp_path):
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    # A private headless session (its runtime directory is btrc-headless.*) is not a desktop.
    headless = "btrc-headless." in os.environ.get("XDG_RUNTIME_DIR", "")
    desktop = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if RunnerIdentity.detect() != "linux" or headless or not desktop:
        pytest.skip(f"requires a physical Linux desktop session (awaiting hardware); run: {DESKTOP_CHECK}")
    script = Path(__file__).resolve().parents[3] / "tools/ui/linux-desktop-check.sh"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    result = subprocess.run([str(script), "--artifacts", str(artifacts)], capture_output=True, text=True, timeout=3600)
    # 3 is explicit incomplete evidence: Orca, GPU reset and physical IME stay deferred.
    assert result.returncode in (0, 3), result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == "btrc.linux-desktop-check/1"
    assert report["trials"]["gui-correctness"]["status"] == "passed", report["trials"]["gui-correctness"]


@pytest.mark.parametrize("ndebug", [False, True], ids=["assertions", "ndebug"])
def test_linux_clipboard_probe_compiles(tmp_path, ndebug):
    """Keep the owned SDK diagnostic buildable without needing a display."""
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    flags = shlex.split(
        subprocess.check_output(["pkg-config", "--cflags", "--libs", "sdl3", "x11"], text=True, timeout=TOOL_TIMEOUT)
    )
    source = Path(__file__).resolve().parents[1] / "native/gui/shell/probes/linux/ClipboardRequestor.c"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            *(["-DNDEBUG"] if ndebug else []),
            str(source),
            *flags,
            "-o",
            str(tmp_path / "ClipboardRequestor"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )


def test_linux_shell_ledger_reports_recorded_failures():
    source = Path(__file__).resolve().parents[3] / "docs/design/native-ui-catalog/evidence/ui1-linux.toml"
    records = LedgerDocument.load(source)
    rollup = LedgerRollup(records)
    boundary = [state for state in rollup.slots.values() if state.subject.id in {"linux-event-boundary", "E40"}]
    assert len(boundary) == 34
    assert sum(state.failed for state in boundary) == 18
    assert sum(state.failed for state in rollup.slots.values()) == 21
    assert all(record.evidence.observed in {None, "passed", "failed", "error"} for record in records)
