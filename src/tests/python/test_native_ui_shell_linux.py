"""The shell journey on the native Wayland Linux provider, by real input; invoke inside headless-session.sh --wayland."""

import os
import sys

import pytest

from src.tests.python.native_ui_shell_fixtures import exercise_shell
from src.tests.runner_capabilities import linux_display_error


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.linux_gui
def test_linux_native_shell(tmp_path, request, frontend, sanitized):
    if sys.platform != "linux":
        pytest.skip("requires the Linux native shell")
    if not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("the Linux GUI provider requires a native Wayland session")
    if error := linux_display_error():
        pytest.skip(error)
    exercise_shell(tmp_path, request, frontend, sanitized, "linux-wayland")


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.linux_gui
def test_first_party_wayland_native_shell(tmp_path, request, frontend):
    if sys.platform != "linux" or not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("requires a Wayland session with virtual pointer and keyboard protocols")
    if os.environ.get("BTRC_UI_PRIVATE_SESSION") != "1":
        pytest.skip("the native shell input probe requires a dedicated test session")
    exercise_shell(tmp_path, request, frontend, False, "linux-wayland-native")
