"""Real SDL shell rows; invoke inside headless-session.sh --x11 or --wayland."""

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


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_native_shell(tmp_path, request, frontend, sanitized):
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    if error := linux_display_error():
        pytest.skip(error)
    provider = "linux-wayland" if os.environ.get("SDL_VIDEODRIVER") == "wayland" else "linux-x11"
    exercise_shell(tmp_path, request, frontend, sanitized, provider)


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
