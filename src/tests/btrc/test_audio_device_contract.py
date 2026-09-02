"""Product-neutral audio-device negotiation and lifecycle conformance."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "AudioDeviceContract.btrc"
API = REPOSITORY / "src" / "stdlib" / "AudioDevice.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compile(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_audio_device_contract_runs_with_both_frontends(semantic_btrcc: Path, tmp_path: Path) -> None:
    generated = {
        "reference": tmp_path / "AudioDeviceReference.c",
        "selfhost": tmp_path / "AudioDeviceSelfhost.c",
    }
    reference = _compile(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-stdlib",
            "--no-cache",
            str(FIXTURE),
            "-o",
            str(generated["reference"]),
        ],
        REPOSITORY,
    )
    selfhost = _compile([str(semantic_btrcc), "--no-stdlib", str(FIXTURE)], REPOSITORY)
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    generated["selfhost"].write_text(selfhost.stdout)

    for frontend, source in generated.items():
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"AudioDevice-{frontend}-{Path(compiler).name}"
            built = _compile(
                [
                    compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    str(source),
                    "-pthread",
                    "-lm",
                    "-o",
                    str(executable),
                ],
                REPOSITORY,
            )
            assert built.returncode == 0, built.stderr
            run = _compile([str(executable)], REPOSITORY)
            assert run.returncode == 0, run.stderr
            assert run.stdout == "PASS AudioDeviceContract\n"
            assert run.stderr == ""


def test_audio_device_contract_keeps_negotiation_and_barrier_explicit() -> None:
    source = API.read_text()
    assert "interface AudioDeviceProvider" in source
    assert "class DuplexAudioSession" in source
    assert "AudioStreamCapability unknown()" in source
    assert "Vector<AudioSampleRateRange>" in source
    assert "minimumBufferFrames" in source
    assert "maximumBufferFrames" in source
    assert "currentBufferFrames" in source
    assert "unsigned long long _inventoryGeneration" in source
    assert "RealtimeAudioFormat? _inputFormat" in source
    assert "RealtimeAudioFormat _outputFormat" in source
    assert "public AudioDeviceOperationOutcome suspend()" in source
    assert "public AudioDeviceOperationOutcome drain()" in source
    assert source.index("self._state = DUPLEX_AUDIO_SESSION_DRAINED") < source.index("self._dispose(self._backend)")
