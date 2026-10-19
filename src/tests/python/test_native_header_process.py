"""A failed native header reader process is reported the same way by both compilers.

A reader that times out or is killed often leaves only an unrelated warning on
stderr: hosted macOS run 39185875448 reported nothing but ``#pragma once in main
file``. Each compiler's process layer therefore appends how the reader ended.
The self-hosted compiler's layer runs here through a small probe program.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.native_imports import NativeHeaderRead, NativeImportError
from src.tests.process_limits import C_COMPILE_TIMEOUT, TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]

WARNING = "Probe.h:1:9: warning: unrelated reader warning"
READER = f"#!/bin/sh\ncat > /dev/null\nprintf '{WARNING}\\n' >&2\n{{ending}}\n"
ENDINGS = {
    "exit": ("exit 3", "native header reader exited with status 3"),
    "signal": ("kill -KILL $$", "native header reader was terminated by signal 9"),
    "timeout": ("exec sleep 60", "native header reader timed out after 1 s"),
}


@pytest.fixture(scope="module")
def process_probe(tmp_path_factory):
    """FeNativeHeaderProcess.readOne, compiled from the self-hosted compiler's own source."""
    if os.name != "posix":
        pytest.skip("the probe readers are POSIX shell scripts")
    root = tmp_path_factory.mktemp("native-header-process")
    source = REPO / "src/tests/btrc/fixtures/NativeHeaderProcessProbe.btrc"
    generated = root / "Probe.c"
    transpiled = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(source), "-o", str(generated)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert transpiled.returncode == 0, transpiled.stderr
    executable = root / "Probe"
    built = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr
    return executable


@pytest.mark.parametrize("ending", sorted(ENDINGS))
def test_failed_reader_reports_its_stderr_and_how_it_ended(process_probe, tmp_path, monkeypatch, ending):
    script, expected = ENDINGS[ending]
    reader = tmp_path / "Reader"
    reader.write_text(READER.format(ending=script), encoding="utf-8")
    reader.chmod(0o755)
    # One second instead of five minutes per selection, for the timeout case.
    monkeypatch.setattr(NativeHeaderRead, "timeout", property(lambda read: 1))
    with pytest.raises(NativeImportError) as reference:
        NativeHeaderRead((str(reader), "--probe"), (0,)).read(dict(os.environ))
    selfhost = subprocess.run(
        [str(process_probe), str(reader), "1000"], capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert str(reference.value) == selfhost.stdout == f"{WARNING}\n{expected}"


def test_a_reader_with_silent_stderr_reports_only_how_it_ended(process_probe, tmp_path):
    reader = tmp_path / "Reader"
    reader.write_text("#!/bin/sh\ncat > /dev/null\nexit 4\n", encoding="utf-8")
    reader.chmod(0o755)
    with pytest.raises(NativeImportError) as reference:
        NativeHeaderRead((str(reader), "--probe"), (0,)).read(dict(os.environ))
    selfhost = subprocess.run(
        [str(process_probe), str(reader), "60000"], capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert str(reference.value) == selfhost.stdout == "native header reader exited with status 4"


def test_the_reader_budget_is_five_minutes_per_selection():
    assert NativeHeaderRead(("reader",), (0,)).timeout == 300
    assert NativeHeaderRead(("reader", "--batch=-"), (0, 1, 2)).timeout == 900
