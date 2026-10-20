"""No AppKit launch: validate the diagnostic recorder with ordinary child processes."""

import json
import os
import subprocess
import sys

import pytest

from src.tests.python.native_ui_shell_diagnostics import MacOSShellDiagnostic


@pytest.fixture
def diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    return {**os.environ, "CI": "true", "BTRC_UI_SHELL_DIAGNOSTICS": str(tmp_path)}


def test_disabled_recorder_delegates_unchanged(monkeypatch):
    observed = []
    expected = object()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (observed.append((args, kwargs)), expected)[1])
    environment = {}
    assert MacOSShellDiagnostic.run(["original"], env=environment, timeout=17) is expected
    assert observed == [((["original"],), {"env": environment, "timeout": 17})]
    assert MacOSShellDiagnostic.debug_flags(environment) == []


@pytest.mark.parametrize("platform,ci", [("linux", "true"), ("darwin", "false")])
def test_opt_in_requires_hosted_macos(tmp_path, monkeypatch, platform, ci):
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(RuntimeError, match="hosted macOS"):
        MacOSShellDiagnostic.directory({"CI": ci, "BTRC_UI_SHELL_DIAGNOSTICS": str(tmp_path)})


def test_recorder_keeps_output_status_and_identity(diagnostic, tmp_path):
    command = [sys.executable, "-c", "import sys; print('receipt'); print('detail', file=sys.stderr); sys.exit(7)"]
    result = MacOSShellDiagnostic.run(command, env=diagnostic, capture_output=True, text=True, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (7, "receipt\n", "detail\n")
    (folder,) = tmp_path.iterdir()
    started = json.loads((folder / "started.json").read_text())
    finished = json.loads((folder / "finished.json").read_text())
    assert started["pid"] == finished["pid"] > 0
    assert started["argv"] == command and started["timeout_seconds"] == 10
    assert started["monotonic_ns"] <= finished["monotonic_ns"]
    assert finished["returncode"] == 7 and finished["timed_out"] is False
    assert (folder / "stdout").read_text() == result.stdout
    assert (folder / "stderr").read_text() == result.stderr
    assert MacOSShellDiagnostic.debug_flags(diagnostic) == ["-g"]


def test_timeout_preserves_partial_output_and_fails(diagnostic, tmp_path):
    command = [sys.executable, "-c", "import time; print('before wait', flush=True); time.sleep(20)"]
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        MacOSShellDiagnostic.run(command, env=diagnostic, capture_output=True, text=True, timeout=0.5)
    assert raised.value.timeout == 0.5 and raised.value.stdout == b"before wait\n"
    (folder,) = tmp_path.iterdir()
    result = json.loads((folder / "finished.json").read_text())
    assert result["timed_out"] is True and result["returncode"] != 0
    assert (folder / "stdout").read_bytes() == raised.value.stdout


def test_failed_sampling_is_retained_with_original_pid(diagnostic, tmp_path, monkeypatch):
    class Child:
        pid = 12345

    observed = []

    def fail(command, **kwargs):
        observed.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial", stderr=b"sample stalled")

    monkeypatch.setattr(subprocess, "run", fail)
    MacOSShellDiagnostic.sample(Child(), tmp_path, 30, 4, diagnostic)
    command, arguments = observed[0]
    assert command[:4] == ["/usr/bin/sample", "12345", "3", "1"]
    assert arguments["timeout"] == 4
    result = json.loads((tmp_path / "sample-30.json").read_text())
    assert result["pid"] == 12345 and result["timed_out"] is True
    assert (tmp_path / "sample-30.stdout").read_bytes() == b"partial"
    assert (tmp_path / "sample-30.stderr").read_bytes() == b"sample stalled"
