"""AppKit shell correctness, including GPU readback on hosted Metal adapters."""

import sys

import pytest

from src.tests.python.native_ui_shell_fixtures import exercise_shell


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_native_shell(tmp_path, request, frontend, sanitized):
    if sys.platform != "darwin":
        pytest.skip("requires macOS AppKit native shell")
    exercise_shell(tmp_path, request, frontend, sanitized, "macos")
