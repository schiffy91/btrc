"""Real reader failures, capture boundaries and process-group cleanup."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.native_imports import NativeHeaderRead, NativeImportError
from src.tests.runner import default_c_compiler

REPO = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Unix SDK-reader host capability")


@pytest.fixture(scope="module", params=["python", "btrc"])
def native_reader_driver(request, selfhost_driver, tmp_path_factory):
    source = REPO / "src/tests/btrc/fixtures/NativeReaderDriver.btrc"
    if request.param == "python":
        return selfhost_driver(source, compile_flags=["-O2", "-pedantic-errors"])
    folder = tmp_path_factory.mktemp("native-reader-driver")
    generated, executable = folder / "driver.c", folder / "driver"
    compiler = request.getfixturevalue("immutable_btrcc")
    result = subprocess.run(
        [str(compiler), str(source), "-o", str(generated)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [
            *shlex.split(os.environ.get("BTRC_CC", default_c_compiler())),
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
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return executable


@pytest.fixture
def reader_process(tmp_path):
    script = tmp_path / "reader.py"
    script.write_text(
        """import os, pathlib, subprocess, sys, time
index, mode, marker = sys.argv[1:]
if index != "1":
    print("response " + index)
    sys.exit(0)
if mode == "failure":
    sys.exit("ReaderFailure")
if mode == "nul":
    sys.stdout.buffer.write(b"valid prefix\\0hidden suffix")
elif mode == "large":
    sys.stdout.buffer.write(b"x" * (8 * 1024 * 1024 + 1))
elif mode == "timeout":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    pathlib.Path(marker).write_text(str(child.pid))
    time.sleep(120)
"""
    )
    return script, tmp_path / "child.pid"


def assert_child_stopped(marker):
    if not marker.exists():
        return
    result = subprocess.run(
        ["/bin/ps", "-o", "stat=", "-p", marker.read_text()], capture_output=True, text=True, check=False
    )
    assert not result.stdout.strip() or result.stdout.lstrip().startswith("Z"), "reader descendant survived"


@pytest.mark.parametrize("mode", ["failure", "nul", "large", "timeout"])
def test_native_reader_host_completes_all_requests_and_reaps_children(native_reader_driver, reader_process, mode):
    script, marker = reader_process
    result = subprocess.run(
        [str(native_reader_driver), sys.executable, str(script), mode, str(marker)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    if mode == "timeout":
        assert marker.exists(), "timeout fixture never started its descendant"
    assert_child_stopped(marker)


@pytest.mark.parametrize("mode", ["failure", "nul", "large", "timeout"])
def test_reference_reader_capture_and_timeout_reap_children(reader_process, mode):
    script, marker = reader_process
    read = NativeHeaderRead((sys.executable, str(script), "1", mode, str(marker)), (0,))
    expected = subprocess.TimeoutExpired if mode == "timeout" else NativeImportError
    with pytest.raises(expected):
        read.read(dict(os.environ))
    if mode == "timeout":
        assert marker.exists(), "timeout fixture never started its descendant"
    assert_child_stopped(marker)
