"""Process-boundary contracts for the bootstrap fixed-point harness."""

import os
import subprocess
import sys
import time

import pytest

from src.tests.btrc.test_bootstrap import _run_process


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
        _run_process(
            [sys.executable, "-c", parent, child, str(marker)],
            timeout=0.2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    assert timeout.value.stdout == "spawned\n"
    time.sleep(1.1)
    assert not marker.exists()
