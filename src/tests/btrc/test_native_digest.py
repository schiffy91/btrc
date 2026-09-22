"""Native SHA and portable target selection retain the managed digest contract.

Portable target C executes on the test host to check backend selection and
algorithm behavior; this does not qualify another platform's native ABI.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.artifacts.archive import TargetCatalog

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def digest_frontend(request):
    if request.param == "reference":
        return [sys.executable, "-m", "src.compiler.python.main"]
    return [str(request.getfixturevalue("immutable_btrcc"))]


@pytest.fixture(scope="module", params=["native", "linux-x64", "windows-x64"])
def digest_driver(request, digest_frontend, tmp_path_factory):
    native = request.param == "native"
    if native and (sys.platform != "darwin" or not os.environ.get("BTRC_NATIVE_HEADER_READER")):
        pytest.skip("native SHA requires macOS and the configured SDK reader")
    target = TargetCatalog().host_target() if native else request.param
    folder = tmp_path_factory.mktemp("native-digest")
    generated = folder / "driver.c"
    executable = folder / "driver"
    environment = dict(os.environ)
    if not native:
        # Portable SHA must not require or launch a native SDK reader.
        environment["BTRC_NATIVE_HEADER_READER"] = str(folder / "reader-must-not-run")
    result = subprocess.run(
        [
            *digest_frontend,
            "--strict-imports",
            "--no-cache",
            "--target",
            target,
            str(ROOT / "src/tests/btrc/fixtures/NativeDigestDriver.btrc"),
            "-o",
            str(generated),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert ("CC_SHA256(" in generated.read_text()) == native
    result = subprocess.run(
        [
            *shlex.split(os.environ.get("BTRC_CC", "cc")),
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return executable


@pytest.mark.parametrize("length", [0, 1, 55, 56, 63, 64, 65, 119, 120, 127, 128, 129, 65535, 65536, 65537, 1048576])
def test_digest_owns_result_and_matches_binary_vectors(digest_driver, tmp_path, length):
    payload = bytes((index * 37 + 11) & 255 for index in range(length))
    source = tmp_path / "input.bin"
    source.write_bytes(payload)
    result = subprocess.run([str(digest_driver), str(source)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == hashlib.sha256(payload).hexdigest() + "\n"
    assert source.read_bytes() == payload
