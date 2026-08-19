"""LLDB-aware debug-adapter bootstrap tests."""

import os
import platform
import subprocess
import types
from pathlib import Path

import pytest
from src.devex.debug.runtime import bootstrap

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_interpreter_probe_imports_the_adapter_and_lldb():
    observed = {}

    def run(command, **options):
        observed["command"] = command
        observed["options"] = options
        return types.SimpleNamespace(returncode=0)

    env = {"PYTHONPATH": "/lldb:/debug"}
    owner = bootstrap.LldbBootstrap(process_runner=run)

    assert owner._can_run_adapter("python", env)
    assert observed == {
        "command": ["python", "-c", "import lldb; import src.devex.debug.protocol.adapter"],
        "options": {
            "env": env,
            "capture_output": True,
            "timeout": bootstrap.LldbBootstrap.PROBE_TIMEOUT_SECONDS,
        },
    }


def test_interpreter_probe_timeout_is_a_failed_candidate():
    def timeout(command, **_options):
        raise subprocess.TimeoutExpired(command, bootstrap.LldbBootstrap.PROBE_TIMEOUT_SECONDS)

    assert not bootstrap.LldbBootstrap(process_runner=timeout)._can_run_adapter("hung-python", {})


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires Apple LLDB")
def test_adapter_imports_with_apple_lldb_python():
    """Apple's LLDB currently binds to Python 3.9, our minimum DAP runtime."""
    env = dict(os.environ)
    env.pop("DEVELOPER_DIR", None)
    env.pop("SDKROOT", None)
    lldb_path = subprocess.run(
        ["/usr/bin/lldb", "-P"],
        env=env,
        capture_output=True,
        text=True,
    )
    if lldb_path.returncode != 0:
        pytest.skip("Apple LLDB Python bridge is unavailable")

    env["PYTHONPATH"] = os.pathsep.join((lldb_path.stdout.strip(), str(REPO_ROOT), env.get("PYTHONPATH", "")))
    imported = subprocess.run(
        ["/usr/bin/python3", "-c", "import lldb; import src.devex.debug.protocol.adapter"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert imported.returncode == 0, imported.stderr
