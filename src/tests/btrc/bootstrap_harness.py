"""Stages of the bootstrap fixed-point gate in test_bootstrap.py.

The gate's process runner, its reference and self-hosted compile steps and
the immutable source snapshot every stage reads. test_bootstrap_harness.py
checks the process-boundary contracts here directly.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import sys

from src.compiler.python.artifacts.archive import TargetCatalog
from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import TOOL_TIMEOUT

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CC = configured_c_compiler()
CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -Wall -Wextra -Werror -pedantic -O2"))


def _absolute_path_flags(flags: list[str]) -> list[str]:
    """Compiles run in scratch directories; repo-relative -I/-include/-isystem
    paths in BTRC_CFLAGS (the Windows compat layer) are resolved against the
    repository so they still land."""
    resolved: list[str] = []
    pending: str | None = None
    for flag in flags:
        if pending is not None:
            candidate = os.path.join(REPO, flag)
            resolved.append(candidate if not os.path.isabs(flag) and os.path.exists(candidate) else flag)
            pending = None
            continue
        if flag in ("-I", "-include", "-isystem"):
            resolved.append(flag)
            pending = flag
            continue
        for prefix in ("-I", "-isystem"):
            if flag.startswith(prefix) and len(flag) > len(prefix):
                path = flag[len(prefix) :]
                candidate = os.path.join(REPO, path)
                if not os.path.isabs(path) and os.path.exists(candidate):
                    flag = prefix + candidate
                break
        resolved.append(flag)
    return resolved


CFLAGS = _absolute_path_flags(CFLAGS)
LDLIBS = shlex.split(os.environ.get("BTRC_LDLIBS", "-lm" if os.name == "nt" else "-lm -lpthread"))
# BTRC_PYTHON overrides the interpreter (Windows CI sets it); otherwise the
# child compiler runs under the interpreter running this test.
PYTHON = shlex.split(os.environ["BTRC_PYTHON"]) if "BTRC_PYTHON" in os.environ else [sys.executable]
BOOTSTRAP_TIMEOUT = int(os.environ.get("BTRC_BOOTSTRAP_TIMEOUT_SECONDS", "1200"))
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
COMPILER_ENTRYPOINT = os.path.join("cli", "WindowsMain.btrc") if os.name == "nt" else "BtrccMain.btrc"
if sys.platform == "darwin" and os.environ.get("BTRC_NATIVE_HEADER_READER"):
    COMPILER_ENTRYPOINT = os.path.join("cli", "MacOSMain.btrc")
COMPILER_HOST_TARGET = TargetCatalog().host_target()


def terminate_process_tree(process: subprocess.Popen) -> None:
    """Kill the bounded command and every descendant it may have spawned."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    elif os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=TOOL_TIMEOUT,
        )
    with contextlib.suppress(ProcessLookupError):
        process.kill()


def run_process(cmd, *, cwd=REPO, timeout, **kwargs):
    """Run one bootstrap stage with a hard, descendant-aware deadline."""
    group_options = (
        {"start_new_session": True}
        if os.name == "posix"
        else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {}
    )
    process = subprocess.Popen(cmd, cwd=cwd, **group_options, **kwargs)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process)
        stdout, stderr = process.communicate()
        timed_out = True
    except BaseException:
        terminate_process_tree(process)
        process.communicate()
        raise
    if timed_out:
        args = process.args
        # A Windows Popen retains the native process handle until the object is
        # released.  Do that before propagating the timeout: the caller may be
        # a TemporaryDirectory context that immediately removes the executable.
        del process
        raise subprocess.TimeoutExpired(
            args,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from None
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def run_stage(cmd, *, cwd=REPO, timeout, **kwargs):
    return run_process(
        cmd,
        cwd=cwd,
        timeout=timeout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )


def transpile_with_python(project_root: str, data_root: str, in_btrc: str, out_c: str) -> None:
    """Stage 1 source: reference compiler transpiles the btrcc source to C."""
    # Use the platform command (overridable with BTRC_PYTHON), not
    # sys.executable: under xdist the worker can be a Nix env-wrapper path that
    # is not directly executable from a subprocess.
    r = run_stage(
        [
            *PYTHON,
            "-m",
            "src.compiler.python.main",
            in_btrc,
            "--strict-imports",
            "--target",
            COMPILER_HOST_TARGET,
            "--no-cache",
            "-o",
            out_c,
        ],
        cwd=project_root,
        env={**os.environ, "BTRC_HOME": data_root, "PYTHONPATH": project_root},
        timeout=BOOTSTRAP_TIMEOUT,
    )
    assert r.returncode == 0 and os.path.exists(out_c), f"btrcpy failed to transpile btrcc:\n{r.stderr[:2000]}"
    # The compiler's own sources analyze clean, as its C builds with -Werror.
    assert "warning:" not in r.stderr, r.stderr[:2000]


def compile_c(src_c: str, out_bin: str, *, workdir: str) -> None:
    r = run_stage(
        [*CC, *CFLAGS, src_c, "-o", out_bin, *LDLIBS],
        cwd=workdir,
        timeout=BOOTSTRAP_TIMEOUT,
    )
    assert r.returncode == 0 and os.path.exists(out_bin), (
        f"{' '.join(CC)} failed to build {os.path.basename(src_c)}:\n{r.stderr[:3000]}"
    )


def run_btrcc(binary: str, in_btrc: str, out_c: str, *, data_root: str, workdir: str) -> None:
    """Run a btrcc binary on a .btrc file, streaming emitted C to out_c."""
    output = os.path.join(REPO, out_c)
    with open(output, "w") as generated:
        r = run_process(
            [binary, "--strict-imports", "--target", COMPILER_HOST_TARGET, in_btrc],
            cwd=workdir,
            env={**os.environ, "BTRC_HOME": data_root},
            stdout=generated,
            stderr=subprocess.PIPE,
            text=True,
            timeout=BOOTSTRAP_TIMEOUT,
        )
    assert r.returncode == 0 and os.path.getsize(output) > 0, (
        f"{os.path.basename(binary)} failed on {in_btrc}:\n{r.stderr[:2000]}"
    )
    # btrcc reports the reference analyzer's warnings, so compiling itself is warning-free too.
    assert "warning:" not in r.stderr, r.stderr[:2000]


def snapshot_compiler_inputs(tmp_dir: str) -> tuple[str, str, str]:
    """Copy one immutable, local source snapshot for every bootstrap stage."""
    project_root = os.path.join(tmp_dir, "snapshot")
    source_root = os.path.join(project_root, "src")
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "build")
    for relative in (
        os.path.join("compiler", "btrc"),
        os.path.join("compiler", "python"),
        "language",
        "stdlib",
    ):
        source = os.path.join(REPO, "src", relative)
        destination = os.path.join(source_root, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copytree(source, destination, ignore=ignored)
    compiler = os.path.join(source_root, "compiler", "btrc", COMPILER_ENTRYPOINT)
    return project_root, source_root, compiler
