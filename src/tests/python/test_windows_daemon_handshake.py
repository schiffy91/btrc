"""Daemon authorization state, independently of native resource verification."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src/runtime/c"
PROBE = ROOT / "src/tests/native/daemon_windows/handshake_probe.c"
STRICT = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    output = tmp_path_factory.mktemp("daemon-handshake") / "probe"
    result = subprocess.run(
        [*configured_c_compiler(), *STRICT, "-I", str(RUNTIME), str(PROBE), "-o", str(output)],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return output


@pytest.mark.parametrize("case", ["happy", "identity", "ordering", "failure"])
def test_authorization_and_failure_transitions(probe, case):
    result = subprocess.run([str(probe), case], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"windows-daemon-handshake {case} PASS\n"


@pytest.mark.parametrize("architecture", ["x86_64", "aarch64"])
def test_handshake_builds_for_windows(architecture, tmp_path):
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("requires the Zig Windows SDK")
    result = subprocess.run(
        [
            zig,
            "cc",
            "-target",
            f"{architecture}-windows-gnu",
            *STRICT,
            "-I",
            str(RUNTIME),
            str(PROBE),
            "-c",
            "-o",
            str(tmp_path / "handshake.o"),
        ],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
