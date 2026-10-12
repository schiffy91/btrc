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
        (
            "UI2LinuxApplicationQuit.btrc",
            "PASS: UI2 Linux native quit cancellation retains every window and queued work",
        ),
        (
            "UI2LinuxApplicationQuitTransactions.btrc",
            "PASS: UI2 Linux native quit revalidates save authority and membership",
        ),
        ("UI2LinuxApplicationQuitCleanup.btrc", "PASS: UI2 Linux quit seals all ingress before reentrant finalizers"),
        (
            "UI2LinuxApplicationQuitRetry.btrc",
            "PASS: UI2 Linux quit retries native publisher cleanup without reopening ingress",
        ),
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
            'manifest-version = 1\n[package]\nname = "ui2LinuxWindowClose"\n'
            '[[native.bindings]]\nmodule = "WindowCloseProbe"\nheader = "WindowCloseProbe.h"\n'
            'language = "c"\nstandard = "c11"\nsymbols = ["ui2PushWindowClose"]\n'
            '[[native.sources]]\npath = "WindowCloseProbe.c"\nlanguage = "c"\n'
            'standard = "c11"\nmodules = ["WindowCloseProbe"]\n'
            '[[native.pkg-config]]\nname = "sdl3"\nmodules = ["WindowCloseProbe"]\n'
        )
        source = package / fixture
    elif fixture in {
        "UI2LinuxApplicationQuit.btrc",
        "UI2LinuxApplicationQuitTransactions.btrc",
        "UI2LinuxApplicationQuitCleanup.btrc",
    }:
        package = tmp_path / "fixture"
        package.mkdir()
        for name in (fixture, "ApplicationQuitProbe.btrc", "ApplicationQuitProbe.h", "ApplicationQuitProbe.c"):
            shutil.copyfile(source.parent / name, package / name)
        (package / "btrc.toml").write_text(
            'manifest-version = 1\n[package]\nname = "ui2LinuxApplicationQuit"\n'
            '[[native.bindings]]\nmodule = "ApplicationQuitProbe"\nheader = "ApplicationQuitProbe.h"\n'
            'language = "c"\nstandard = "c11"\nsymbols = ["ui2PushApplicationQuit"]\n'
            '[[native.sources]]\npath = "ApplicationQuitProbe.c"\nlanguage = "c"\n'
            'standard = "c11"\nmodules = ["ApplicationQuitProbe"]\n'
            '[[native.pkg-config]]\nname = "sdl3"\nmodules = ["ApplicationQuitProbe"]\n'
        )
        source = package / fixture
    elif fixture == "UI2LinuxApplicationQuitRetry.btrc":
        package = tmp_path / "fixture"
        package.mkdir()
        for name in (fixture, "ApplicationQuitFaults.btrc", "ApplicationQuitFaults.h", "ApplicationQuitFaults.c"):
            shutil.copyfile(source.parent / name, package / name)
        (package / "btrc.toml").write_text(
            'manifest-version = 1\n[package]\nname = "ui2LinuxApplicationQuitRetry"\n'
            '[[native.bindings]]\nmodule = "ApplicationQuitFaults"\nheader = "ApplicationQuitFaults.h"\n'
            'language = "c"\nstandard = "c11"\n'
            'symbols = ["ui2ArmQuitPublisherFault", "ui2DisarmQuitPublisherFault", "ui2QuitPublisherFaultCount"]\n'
            '[[native.sources]]\npath = "ApplicationQuitFaults.c"\nlanguage = "c"\n'
            'standard = "c11"\nmodules = ["ApplicationQuitFaults"]\n'
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
    if fixture == "UI2LinuxControls.btrc":
        assert "PASS: UI2 Linux range authority and ordered native slider interactions" in result.stdout
