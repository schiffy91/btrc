"""Real Linux grid replacement, retained pixels and child ownership."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_provider_program, provider_environment, require_linux_reader
from src.tests.runner_capabilities import linux_display_error


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.linux_gui
def test_linux_grid_replacement(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    root = Path(__file__).resolve().parents[3]
    program = root / "src/tests/native/gui/layout/linux/LinuxGridReplacement.btrc"
    executable = build_provider_program(
        program, tmp_path, frontend, sanitized, request, data_root=request.getfixturevalue("gui_provider_root")
    )
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=45,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: linux grid replacement preserves rejected child and pixels" in result.stdout, result.stdout
