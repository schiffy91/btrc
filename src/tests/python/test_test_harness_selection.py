"""Fail-closed compiler-matrix selection for the language test harness."""

import os
from pathlib import Path

import pytest

from src.tests.conftest import _configured_test_btrcc, _parse_compilers


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("both", ["python", "btrc"]),
        ("python", ["python"]),
        ("btrc", ["btrc"]),
        ("python,btrc", ["python", "btrc"]),
        (" btrc , python ", ["btrc", "python"]),
        ("python,python", ["python"]),
    ),
)
def test_parse_compilers(raw: str, expected: list[str]) -> None:
    assert _parse_compilers(raw) == expected


@pytest.mark.parametrize("raw", ("", " ", "unknown", "python,", "both,python"))
def test_invalid_compiler_selection_raises_usage_error(raw: str) -> None:
    with pytest.raises(pytest.UsageError):
        _parse_compilers(raw)


def test_prebuilt_btrcc_override_is_optional_and_resolves_absolute_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BTRC_TEST_BTRCC", raising=False)
    assert _configured_test_btrcc() is None

    binary = tmp_path / "btrcc"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("BTRC_TEST_BTRCC", str(binary))
    assert _configured_test_btrcc() == binary.resolve()


@pytest.mark.parametrize("configured", ("", "relative/btrcc"))
def test_prebuilt_btrcc_override_rejects_non_absolute_paths(
    configured: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BTRC_TEST_BTRCC", configured)
    with pytest.raises(pytest.UsageError, match="absolute"):
        _configured_test_btrcc()


def test_prebuilt_btrcc_override_rejects_missing_or_non_executable_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing-btrcc"
    monkeypatch.setenv("BTRC_TEST_BTRCC", str(missing))
    with pytest.raises(pytest.UsageError, match="does not resolve"):
        _configured_test_btrcc()

    if os.name != "nt":
        binary = tmp_path / "btrcc"
        binary.write_text("not executable\n", encoding="utf-8")
        binary.chmod(0o644)
        monkeypatch.setenv("BTRC_TEST_BTRCC", str(binary))
        with pytest.raises(pytest.UsageError, match="not executable"):
            _configured_test_btrcc()
