"""Bounded semantic capture through Linux control and forest admission."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_provider_program, provider_environment, require_linux_reader
from src.tests.runner_capabilities import linux_display_error

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_linux_capture_admission(tmp_path, request, gui_provider_root, frontend, sanitized):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    executable = build_provider_program(
        ROOT / "src/tests/native/gui/ui2/probes/linux/UI2LinuxCapture.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        data_root=gui_provider_root,
    )
    ran = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=60,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(ran.stdout)
    (tmp_path / "stderr.txt").write_text(ran.stderr)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "PASS: Linux capture admission and atomic forest routes" in ran.stdout
