"""The pinned SDL's X11 clipboard owner survives a requestor that is already gone.

SDL 3.4.10 answers a selection request by writing the requestor's property; if
the requestor destroyed its window first, Xlib's default handler exits on
BadWindow (X_ChangeProperty). That made `test_linux_gui_controls` fail
intermittently when parallel workers shared one X display. The flake's SDL
carries nix/sdl3-x11-selection-requestor.patch, and ClipboardRequestor.c forces
the interleaving deterministically.
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.runner_capabilities import linux_display_error

PROBE = Path(__file__).resolve().parents[1] / "native/gui/shell/probes/linux/ClipboardRequestor.c"


@pytest.fixture(scope="module")
def requestor_probe(tmp_path_factory) -> Path:
    if sys.platform != "linux":
        pytest.skip("requires Linux X11 SDL")
    if error := linux_display_error():
        pytest.skip(error)
    if not os.environ.get("DISPLAY"):
        pytest.skip("requires Linux X11 SDL: no DISPLAY")
    flags = shlex.split(
        subprocess.check_output(["pkg-config", "--cflags", "--libs", "sdl3", "x11"], text=True, timeout=TOOL_TIMEOUT)
    )
    binary = tmp_path_factory.mktemp("clipboard-requestor") / "ClipboardRequestor"
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", str(PROBE), *flags, "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    return binary


@pytest.mark.parametrize("destroyed", [False, True], ids=["live-requestor", "destroyed-requestor"])
def test_sdl_clipboard_owner_survives_its_requestor(requestor_probe: Path, destroyed: bool) -> None:
    completed = subprocess.run(
        [str(requestor_probe), "1" if destroyed else "0"],
        env={**os.environ, "SDL_VIDEODRIVER": "x11"},
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert f"destroyed={int(destroyed)}" in output
    assert "clipboard owner survived dispatch" in output
