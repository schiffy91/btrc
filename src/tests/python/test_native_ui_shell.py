"""Portable shell exclusions are diagnostics/unavailability, never fake passes."""

import pytest

from src.tests.python.native_ui_shell_fixtures import SHELL, transpile, write_evidence


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_windows_native_shell_provider_missing(tmp_path, request, frontend):
    result = transpile(
        SHELL / "NativeShell.btrc", tmp_path / "Shell.c", tmp_path / "Shell.json", frontend, request, "windows-x86_64"
    )
    assert result.returncode != 0
    assert "has no provider for target windows-x86_64" in result.stderr, result.stderr
    write_evidence(
        "native-shell-provider-missing",
        "windows",
        frontend,
        False,
        {"diagnostic": result.stderr},
        status="unavailable",
        reason="GUI provider is not implemented",
    )


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
    assert (SHELL / "probes/macos/ShellProbe.h").read_bytes() == (SHELL / "probes/linux/ShellProbe.h").read_bytes()


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
