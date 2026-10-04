"""Real SDL shell rows; invoke inside headless-session.sh --x11 or --wayland."""

import os
import sys

import pytest

from src.tests.python.native_ui_shell_fixtures import exercise_shell
from src.tests.runner_capabilities import linux_display_error


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_native_shell(tmp_path, request, frontend, sanitized):
    if sys.platform != "linux":
        pytest.skip("requires Linux SDL native shell")
    if error := linux_display_error():
        pytest.skip(error)
    provider = "linux-wayland" if os.environ.get("SDL_VIDEODRIVER") == "wayland" else "linux-x11"
    exercise_shell(tmp_path, request, frontend, sanitized, provider)
