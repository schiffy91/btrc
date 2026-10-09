"""Real Linux parent-layout dispatch, scroll offsets and GPU pixel evidence."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_provider_program, provider_environment, require_linux_reader
from src.tests.runner_capabilities import linux_display_error


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize(
    "fixture,arguments,expected",
    [
        ("LinuxGridScrollResize.btrc", (), "PASS: linux grid scroll resize"),
        ("LinuxStackScrollResize.btrc", ("0",), "PASS: linux stack scroll resize 0"),
        ("LinuxStackScrollResize.btrc", ("1",), "PASS: linux stack scroll resize 1"),
    ],
    ids=["grid", "row", "column"],
)
@pytest.mark.linux_gui
def test_linux_layout_resize(tmp_path, request, frontend, sanitized, fixture, arguments, expected):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    root = Path(__file__).resolve().parents[3]
    program = root / "src/tests/native/gui/layout/linux" / fixture
    executable = build_provider_program(
        program, tmp_path, frontend, sanitized, request, data_root=request.getfixturevalue("gui_provider_root")
    )
    result = subprocess.run(
        [str(executable), *arguments],
        capture_output=True,
        text=True,
        timeout=45,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout, result.stdout
