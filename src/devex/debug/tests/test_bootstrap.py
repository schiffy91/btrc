"""Compatibility tests for the LLDB-aware debug-adapter bootstrap."""

import os
import platform
import subprocess
import types
from pathlib import Path

import bootstrap
import pytest

DEBUG_DIR = Path(__file__).resolve().parents[1]


def test_interpreter_probe_imports_the_adapter_and_lldb(monkeypatch):
    observed = {}

    def run(command, **options):
        observed["command"] = command
        observed["options"] = options
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    env = {"PYTHONPATH": "/lldb:/debug"}

    assert bootstrap._can_run_adapter("python", env)
    assert observed == {
        "command": ["python", "-c", "import lldb; import adapter"],
        "options": {"env": env, "capture_output": True},
    }


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

    env["PYTHONPATH"] = os.pathsep.join((lldb_path.stdout.strip(), str(DEBUG_DIR), env.get("PYTHONPATH", "")))
    imported = subprocess.run(
        ["/usr/bin/python3", "-c", "import lldb; import adapter"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert imported.returncode == 0, imported.stderr
