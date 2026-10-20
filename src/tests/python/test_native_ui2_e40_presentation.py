"""Exercise the actual portable presentation ledger without AppKit or a display."""

import subprocess
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler

FIXTURES = Path(__file__).resolve().parents[1] / "native/gui/ui2/probes/macos/e40"


@pytest.fixture(scope="module")
def presentation_ledger(tmp_path_factory):
    executable = tmp_path_factory.mktemp("presentation-ledger") / "ledger"
    built = subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(FIXTURES / "PresentationTest.c"),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return executable


@pytest.mark.parametrize(
    "mode",
    range(11),
    ids=[
        "drop-retry-positive",
        "all-dropped-remains-pending",
        "late-acquired-callback",
        "stale-sequence",
        "retry-unavailable",
        "duplicate-positive",
        "presentation-before-admission",
        "invalid-native-timestamp",
        "retry-acquired-unavailable-late-callback",
        "rejected-receipt-replaced",
        "retry-acquired-unavailable-positive",
    ],
)
def test_presentation_receipt_attempt_lifetime(presentation_ledger, mode):
    result = subprocess.run([str(presentation_ledger), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
