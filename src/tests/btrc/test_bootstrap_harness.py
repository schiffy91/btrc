"""Process-boundary contracts for the bootstrap fixed-point harness."""

import gc
import os
import shutil
import subprocess
import sys
import time
import weakref

import pytest

from src.tests.btrc import test_bootstrap as bootstrap


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_stage_timeout_kills_spawned_descendants(tmp_path) -> None:
    marker = tmp_path / "escaped-child"
    child = "import pathlib,sys,time; time.sleep(1); pathlib.Path(sys.argv[1]).write_text('escaped')"
    parent = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
        "print('spawned', flush=True); "
        "time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired) as timeout:
        bootstrap._run_process(
            [sys.executable, "-c", parent, child, str(marker)],
            timeout=0.2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    assert timeout.value.stdout == "spawned\n"
    time.sleep(1.1)
    assert not marker.exists()


def test_stage_timeout_releases_process_before_propagating(monkeypatch) -> None:
    processes = []

    class TimedOutProcess:
        pid = 1
        returncode = -1

        def __init__(self, args) -> None:
            self.args = args

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return b"", b""

    def process_factory(args, **_kwargs):
        process = TimedOutProcess(args)
        processes.append(weakref.ref(process))
        return process

    monkeypatch.setattr(bootstrap.subprocess, "Popen", process_factory)
    monkeypatch.setattr(bootstrap, "_terminate_process_tree", lambda _process: None)

    with pytest.raises(subprocess.TimeoutExpired):
        bootstrap._run_process(["timed-out"], timeout=0.01)

    gc.collect()
    assert processes[0]() is None


@pytest.mark.skipif(os.name != "nt", reason="native Windows executable-release contract")
def test_stage_timeout_releases_native_windows_executable(tmp_path) -> None:
    executable = tmp_path / "timed-out-python.exe"
    shutil.copy2(sys.executable, executable)

    with pytest.raises(subprocess.TimeoutExpired):
        bootstrap._run_process(
            [str(executable), "-c", "import time; time.sleep(30)"],
            timeout=0.2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    executable.unlink()
