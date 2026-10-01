"""LLDB-aware debug-adapter bootstrap tests."""

import io
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


class _Executed(Exception):
    """Stands in for a successful execve, which never returns."""


class _RecordedExecve:
    """Record the adapter re-exec instead of replacing the test process."""

    def __init__(self):
        self.call = None

    def __call__(self, path, argv, environment):
        self.call = {"path": path, "argv": argv, "environment": environment}
        raise _Executed


def _lldb_unimportable(name):
    raise ImportError(name)


def test_lldb_resolution_drops_the_build_sdk_selectors():
    """A build shell's DEVELOPER_DIR and SDKROOT misdirect Apple's xcrun shims."""

    shell = {
        "DEVELOPER_DIR": "/nix/store/apple-sdk",
        "SDKROOT": "/nix/store/apple-sdk/MacOSX.sdk",
        "PATH": "/nix/bin:/usr/bin",
        "PYTHONPATH": "/project",
    }
    observed = {"probes": []}

    def check_output(command, **options):
        observed["lldb"] = (command, options)
        return "/Xcode/LLDB.framework/Resources/Python\n"

    def run(command, **options):
        observed["probes"].append((command[0], options["env"]))
        return types.SimpleNamespace(returncode=0 if command[0] == "/usr/bin/python3" else 1)

    execve = _RecordedExecve()
    owner = bootstrap.LldbBootstrap(
        environment=shell,
        arguments=("--trace",),
        executable="/nix/bin/python3.14",
        check_output=check_output,
        process_runner=run,
        path_lookup={"lldb": "/usr/bin/lldb", "python3": "/nix/bin/python3"}.get,
        execve=execve,
        module_importer=_lldb_unimportable,
    )

    with pytest.raises(_Executed):
        owner.ensure_lldb()

    command, options = observed["lldb"]
    assert command == ["/usr/bin/lldb", "-P"]
    assert options["env"] == {"PATH": "/nix/bin:/usr/bin", "PYTHONPATH": "/project"}
    adapter_environment = {
        "PATH": "/nix/bin:/usr/bin",
        "PYTHONPATH": os.pathsep.join(("/Xcode/LLDB.framework/Resources/Python", str(REPO_ROOT), "/project")),
        bootstrap.LldbBootstrap.GUARD_VARIABLE: "1",
    }
    assert observed["probes"] == [("/usr/bin/python3", adapter_environment)]
    assert execve.call == {
        "path": "/usr/bin/python3",
        "argv": ["/usr/bin/python3", "-m", "src.devex.debug", "--trace"],
        "environment": adapter_environment,
    }
    # The bootstrap's own record of the shell is untouched: only lldb's resolution drops them.
    assert owner.environment["DEVELOPER_DIR"] == "/nix/store/apple-sdk"


def test_interpreter_probe_timeout_is_a_failed_candidate():
    def timeout(command, **_options):
        raise subprocess.TimeoutExpired(command, bootstrap.LldbBootstrap.PROBE_TIMEOUT_SECONDS)

    assert not bootstrap.LldbBootstrap(process_runner=timeout)._can_run_adapter("hung-python", {})


def test_darwin_debugger_access_rejects_disabled_developer_mode():
    observed = {}

    def run(command, **options):
        observed["command"] = command
        observed["options"] = options
        return types.SimpleNamespace(returncode=0, stdout="Developer mode is currently disabled.\n")

    errors = io.StringIO()
    owner = bootstrap.LldbBootstrap(
        platform_name="darwin",
        process_runner=run,
        error_stream=errors,
    )

    with pytest.raises(SystemExit):
        owner.ensure_debugger_access()

    assert observed == {
        "command": ["/usr/sbin/DevToolsSecurity", "-status"],
        "options": {
            "capture_output": True,
            "text": True,
            "timeout": bootstrap.LldbBootstrap.PROBE_TIMEOUT_SECONDS,
        },
    }
    assert "DevToolsSecurity -enable" in errors.getvalue()


def test_darwin_debugger_access_accepts_enabled_developer_mode():
    def run(_command, **_options):
        return types.SimpleNamespace(returncode=0, stdout="Developer mode is currently enabled.\n")

    owner = bootstrap.LldbBootstrap(platform_name="darwin", process_runner=run)

    assert owner.debugger_access_available()


def test_non_darwin_debugger_access_needs_no_host_probe():
    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("non-Darwin hosts must not run DevToolsSecurity")

    owner = bootstrap.LldbBootstrap(platform_name="linux", process_runner=unexpected_probe)

    assert owner.debugger_access_available()


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


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires Apple LLDB")
def test_bootstrap_finds_apple_lldb_under_a_build_shell_sdk(tmp_path):
    """The real shims, under the developer directory a Nix shell exports: one that carries no lldb."""

    shell = {name: value for name, value in os.environ.items() if name != bootstrap.LldbBootstrap.GUARD_VARIABLE}
    shell.update(DEVELOPER_DIR=str(tmp_path), SDKROOT=str(tmp_path / "MacOSX.sdk"))
    execve = _RecordedExecve()
    owner = bootstrap.LldbBootstrap(environment=shell, execve=execve, module_importer=_lldb_unimportable)
    if subprocess.run(["/usr/bin/lldb", "-P"], env=owner.lldb_environment(), capture_output=True).returncode != 0:
        pytest.skip("Apple LLDB Python bridge is unavailable")

    with pytest.raises(_Executed):
        owner.ensure_lldb()

    assert execve.call["argv"][1:3] == ["-m", "src.devex.debug"]
    assert not {"DEVELOPER_DIR", "SDKROOT"} & set(execve.call["environment"])
    imported = subprocess.run(
        [execve.call["path"], "-c", "import lldb; import src.devex.debug.protocol.adapter"],
        env=execve.call["environment"],
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
