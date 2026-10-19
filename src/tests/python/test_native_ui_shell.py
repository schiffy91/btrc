"""Portable shell exclusions are diagnostics/unavailability, never fake passes."""

import pytest

from src.tests.python.native_ui_shell_fixtures import SHELL, write_evidence

# The Windows rows live in test_native_ui_shell_windows.py (CX-UIA-15).


@pytest.mark.parametrize("target", ["ios", "android"])
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_mobile_shell_unavailable(target, frontend):
    write_evidence(
        "native-shell",
        target,
        frontend,
        False,
        {"executed": False},
        status="unavailable",
        reason="Native shell awaits Stage 24 target support and the platform shell packet",
    )


def test_shell_probe_headers_share_one_contract():
    contract = (SHELL / "probes/linux/ShellProbe.h").read_bytes()
    for platform in ("macos", "windows"):
        assert (SHELL / f"probes/{platform}/ShellProbe.h").read_bytes() == contract, platform


def test_macos_diagnostics_preserve_timeout_and_continue(tmp_path, monkeypatch):
    import subprocess

    from src.tests.python.native_ui_shell_fixtures import diagnose_macos_retention

    calls = []

    def run(command, **kwargs):
        calls.append(kwargs["env"])
        if len(calls) == 2:
            raise subprocess.TimeoutExpired(command, 60, output=b"partial stdout", stderr=b"survivor before timeout")
        return subprocess.CompletedProcess(command, 1, "measured failure", "provider survivor")

    monkeypatch.setattr(subprocess, "run", run)
    observations = diagnose_macos_retention(tmp_path / "fixture", tmp_path, {"PRESERVED": "yes"})
    assert len(calls) == len(observations) == 4
    assert all(environment["PRESERVED"] == "yes" for environment in calls)
    assert observations[1]["returncode"] == "timeout"
    assert observations[1]["stderr"] == "survivor before timeout"
    assert (tmp_path / "diagnostic-ax-0-wheel-1/stdout").read_text() == "partial stdout"
    assert (tmp_path / "diagnostic-ax-0-wheel-0/stderr").read_text() == "provider survivor"


def test_shell_acceptance_cannot_inherit_disabled_native_probes(monkeypatch):
    from src.tests.python import native_ui_shell_fixtures as shell

    ambient = {"BTRC_UI_SHELL_NO_AX": "1", "BTRC_UI_SHELL_NO_SCROLL": "1", "KEEP_RUNNER_SETTING": "yes"}
    monkeypatch.setattr(shell, "apple_environment", lambda: ambient)
    monkeypatch.setattr(shell, "provider_environment", lambda sanitized: ambient)
    acceptance = shell.shell_environment(False)
    assert "BTRC_UI_SHELL_NO_AX" not in acceptance
    assert "BTRC_UI_SHELL_NO_SCROLL" not in acceptance
    assert acceptance["KEEP_RUNNER_SETTING"] == "yes"
    assert ambient["BTRC_UI_SHELL_NO_SCROLL"] == "1"
