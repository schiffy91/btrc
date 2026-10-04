"""Portable shell exclusions are diagnostics/unavailability, never fake passes."""

import pytest

from src.tests.python.native_ui_shell_fixtures import SHELL, transpile, write_evidence


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_windows_native_shell_provider_missing(tmp_path, request, frontend):
    result = transpile(
        SHELL / "NativeShell.btrc", tmp_path / "Shell.c", tmp_path / "Shell.json", frontend, request, "windows-x86_64"
    )
    assert result.returncode != 0
    assert "provider" in result.stderr.lower(), result.stderr
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
