"""Approved UI2 Linux outcomes through the real SDL provider, never a fake loop."""

import json
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_provider_program, provider_environment, require_linux_reader
from src.tests.runner_capabilities import linux_display_error

pytestmark = pytest.mark.linux_gui

CYCLE_SUITES = {
    "UI2LinuxLifecycle.btrc": ("lifecycle", "windows"),
    "UI2LinuxWindowClose.btrc": ("window-close", "windows"),
    "UI2LinuxWindowQuit.btrc": ("window-quit", "windows"),
    "UI2LinuxExecutor.btrc": ("hosted-suspension", "pending"),
}


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize(
    ("fixture", "marker"),
    [
        ("UI2LinuxSlider.btrc", "PASS: UI2 Linux slider drag cancellation and keyboard intents"),
        ("UI2LinuxWindowClose.btrc", "PASS: UI2 Linux native close preserves transaction and save authority"),
        ("UI2LinuxWindowQuit.btrc", "PASS: UI2 Linux native quit holds and revalidates all windows"),
        ("UI2LinuxExecutor.btrc", "PASS: UI2 Linux worker native wake and hosted suspension"),
        ("UI2LinuxHostFailure.btrc", "PASS: UI2 Linux host failures stay contained through drain"),
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
    if fixture in ("UI2LinuxWindowClose.btrc", "UI2LinuxWindowQuit.btrc", "UI2LinuxLifecycle.btrc"):
        package = tmp_path / "fixture"
        package.mkdir()
        for name in (fixture, "WindowCloseProbe.btrc", "WindowCloseProbe.h", "WindowCloseProbe.c"):
            shutil.copyfile(source.parent / name, package / name)
        if fixture in ("UI2LinuxWindowClose.btrc", "UI2LinuxWindowQuit.btrc"):
            shutil.copyfile(source.parent / "LinuxCancelState.btrc", package / "LinuxCancelState.btrc")
        (package / "btrc.toml").write_text(
            'manifest-version = 1\n[package]\nname = "ui2LinuxWindowClose"\n'
            '[[native.bindings]]\nmodule = "WindowCloseProbe"\nheader = "WindowCloseProbe.h"\n'
            'language = "c"\nstandard = "c11"\nsymbols = ["ui2PushWindowClose", "ui2PushQuit", "ui2PushPointerMotion", "ui2NativeWindowCount"]\n'
            '[[native.sources]]\npath = "WindowCloseProbe.c"\nlanguage = "c"\n'
            'standard = "c11"\nmodules = ["WindowCloseProbe"]\n'
            '[[native.pkg-config]]\nname = "sdl3"\nmodules = ["WindowCloseProbe"]\n'
        )
        source = package / fixture
        if fixture == "UI2LinuxLifecycle.btrc":
            source.write_text(source.read_text().replace("../../PendingImageGate.btrc", "PendingImageGate.btrc"))
            shutil.copyfile(root / "src/tests/native/gui/ui2/PendingImageGate.btrc", package / "PendingImageGate.btrc")
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
        timeout=600 if fixture in CYCLE_SUITES else 30,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
    if fixture == "UI2LinuxLifecycle.btrc":
        assert (
            result.stdout.splitlines().count(
                "UI2_E29 pending_image cycles=100 commit=34 rollback_step0=33 rollback_step1=33 late_closed=100"
            )
            == 1
        )
    if fixture in {"UI2LinuxWindowClose.btrc", "UI2LinuxWindowQuit.btrc"}:
        name = CYCLE_SUITES[fixture][0]
        entries = "native,program" if name == "window-close" else "native-quit"
        states = [line for line in result.stdout.splitlines() if line.startswith("UI2_CANCEL_STATE ")]
        assert states == [
            f"UI2_CANCEL_STATE {name} {cycle} entries={entries} "
            "draft=kept focus=kept selection=kept anchor=kept destination=kept"
            for cycle in range(1, 101)
        ], result.stdout
    if fixture in CYCLE_SUITES:
        name, resource = CYCLE_SUITES[fixture]
        actual = [line for line in result.stdout.splitlines() if line.startswith("UI2_CYCLE ")]
        expected = [f"UI2_CYCLE {name} {cycle} {resource}=0" for cycle in range(1, 101)]
        assert actual == expected, result.stdout
        policies = [line for line in result.stdout.splitlines() if line.startswith("UI2_POLICY ")]
        assert len(policies) == 1 and policies[0].startswith(f"UI2_POLICY {name} ")
        (tmp_path / "acceptance-cycles.json").write_text(
            json.dumps(
                {
                    "fixture": fixture,
                    "frontend": frontend,
                    "sanitized": sanitized,
                    "cycles": 100,
                    "resource": resource,
                    "residual": 0,
                    "policy": policies[0],
                    "scope": "SDL windows and provider callback/credit assertions; no private-memory census",
                },
                indent=2,
            )
        )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("state", ["open", "closed"])
def test_linux_ui2_callback_scope_release_requires_executor(tmp_path, request, frontend, sanitized, state):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    root = Path(__file__).resolve().parents[3]
    executable = build_provider_program(
        root / "src/tests/native/gui/ui2/probes/linux/UI2LinuxAffineRelease.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        data_root=request.getfixturevalue("gui_provider_root"),
    )
    environment = provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1")
    for mode in ("ui", state):
        result = subprocess.run([str(executable), mode], capture_output=True, text=True, timeout=30, env=environment)
        (tmp_path / f"{mode}-stdout.txt").write_text(result.stdout)
        (tmp_path / f"{mode}-stderr.txt").write_text(result.stderr)
        (tmp_path / f"{mode}-result.json").write_text(
            json.dumps({"state": mode, "returncode": result.returncode, "frontend": frontend, "sanitized": sanitized})
        )
        if mode == "ui":
            assert result.returncode == 0, result.stdout + result.stderr
            assert "PASS: UI2 closed affine owner released on UI thread" in result.stdout
        else:
            assert "UI2_FINAL_RELEASE worker-entered" in result.stderr, result.stderr
            assert result.returncode == -signal.SIGABRT, result.stdout + result.stderr
            assert "Callback scope destruction requires its creating thread" in result.stderr
            assert "UI2_FINAL_RELEASE worker-returned" not in result.stderr
            assert "UI2_FINAL_RELEASE joined" not in result.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("state", ["open", "closed"])
def test_linux_ui2_final_release_requires_executor(tmp_path, request, frontend, sanitized, state):
    """Release the actual provider's last reference, without a UI owner alias."""
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    root = Path(__file__).resolve().parents[3]
    executable = build_provider_program(
        root / "src/tests/native/gui/ui2/probes/linux/UI2LinuxFinalRelease.btrc",
        tmp_path,
        frontend,
        sanitized,
        request,
        data_root=request.getfixturevalue("gui_provider_root"),
    )
    result = subprocess.run(
        [str(executable), state],
        capture_output=True,
        text=True,
        timeout=30,
        env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "owner": "LinuxApplication",
                "state": state,
                "returncode": result.returncode,
                "frontend": frontend,
                "sanitized": sanitized,
            },
            indent=2,
        )
    )
    assert "UI2_FINAL_RELEASE worker-entered" in result.stderr, result.stderr
    if state == "closed":
        assert result.returncode == 0, result.stdout + result.stderr
        assert "UI2_FINAL_RELEASE worker-returned" in result.stderr
        assert "UI2_FINAL_RELEASE joined failed=0" in result.stderr
    else:
        assert result.returncode == -signal.SIGABRT, result.stdout + result.stderr
        assert "Native application destroyed before subtree cleanup completed" in result.stderr
        assert "UI2_FINAL_RELEASE worker-returned" not in result.stderr
        assert "UI2_FINAL_RELEASE joined" not in result.stderr
