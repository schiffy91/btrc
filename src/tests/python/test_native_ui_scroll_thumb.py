"""Real Linux scrollbar pixels and input, through both compiler frontends."""

import subprocess

import pytest

from src.tests.python.linux_provider_fixtures import (
    ROOT,
    build_provider_program,
    provider_environment,
    require_linux_reader,
)
from src.tests.runner_capabilities import linux_display_error


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_scroll_thumb_bounds(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    executable = build_provider_program(
        ROOT / "src/tests/native/gui/controls/linux/ScrollThumbBounds.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        data_root=request.getfixturevalue("gui_provider_root"),
    )
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=180,
        env={**provider_environment(sanitized), "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: linux scroll thumb bounds and input" in result.stdout
