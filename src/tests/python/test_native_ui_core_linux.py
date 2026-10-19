"""Approved UI2 Linux outcomes through the real SDL provider, never a fake loop."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_provider_program, provider_environment, require_linux_reader
from src.tests.runner_capabilities import linux_display_error


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize(
    ("fixture", "marker"),
    [
        ("UI2LinuxWindowClose.btrc", "PASS: UI2 Linux native close preserves transaction and save authority"),
        ("UI2LinuxExecutor.btrc", "PASS: UI2 Linux worker native wake and hosted suspension"),
        ("UI2LinuxLifecycle.btrc", "PASS: UI2 Linux inherited eligibility and scoped observations"),
        ("UI2LinuxControls.btrc", "PASS: UI2 Linux two-axis geometry and native wheel observations"),
    ],
)
def test_linux_ui2_executor_and_lifecycle(tmp_path, request, frontend, sanitized, fixture, marker):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    root = Path(__file__).resolve().parents[3]
    source = root / "src/tests/native/gui/ui2/probes/linux" / fixture
    if fixture == "UI2LinuxWindowClose.btrc":
        package = tmp_path / "fixture"
        package.mkdir()
        for name in (fixture, "WindowCloseProbe.btrc", "WindowCloseProbe.h", "WindowCloseProbe.c"):
            shutil.copyfile(source.parent / name, package / name)
        (package / "btrc.toml").write_text(
            '[package]\nname = "ui2LinuxWindowClose"\n'
            '[[native.bindings]]\nmodule = "WindowCloseProbe"\nheader = "WindowCloseProbe.h"\n'
            'language = "c"\nstandard = "c11"\nsymbols = ["ui2PushWindowClose"]\n'
            '[[native.sources]]\npath = "WindowCloseProbe.c"\nlanguage = "c"\n'
            'standard = "c11"\nmodules = ["WindowCloseProbe"]\n'
            '[[native.pkg-config]]\nname = "sdl3"\nmodules = ["WindowCloseProbe"]\n'
        )
        source = package / fixture
    executable = build_provider_program(
        source,
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
        timeout=30,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
