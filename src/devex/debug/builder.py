"""Build a .btrc program into a debuggable native binary.

Transpiles with ``--debug`` (so the C carries ``#line`` directives back to the
.btrc source) and compiles with ``-g`` so the binary's DWARF references btrc
source — giving lldb native btrc breakpoints and stepping.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field


class BuildError(RuntimeError):
    pass


_BUILD_TIMEOUT_SECONDS = 300
_TERMINATION_TIMEOUT_SECONDS = 2
_IS_WINDOWS = os.name == "nt"


@dataclass
class BuildArtifact:
    """One debug executable and the directory that owns its generated files."""

    executable: str
    directory: str
    _temporary_directory: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove owned temporary files; caller-provided output dirs are kept."""
        if self._temporary_directory is None:
            return
        self._temporary_directory.cleanup()
        self._temporary_directory = None


def build(program, *, btrcpy_cmd, cc="cc", out_dir=None, cflags=None, cwd=None):
    """Return an owned :class:`BuildArtifact` for *program*.

    btrcpy_cmd: argv list that runs the btrc compiler (e.g.
        ["python3", "-m", "src.compiler.python.main"] or ["/path/bin/btrcpy"]).
    cwd: working directory for the transpile step — required for the
        ``-m src.compiler.python.main`` form to resolve from a source checkout.
    """
    program = os.path.abspath(program)
    if not os.path.isfile(program):
        raise BuildError(f"program not found: {program}")
    temporary_directory = None
    if out_dir is None:
        temporary_directory = tempfile.TemporaryDirectory(prefix="btrc-debug-")
        out_dir = temporary_directory.name
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(program))[0]
    c_path = os.path.join(out_dir, stem + ".c")
    bin_path = os.path.join(out_dir, stem)
    artifact = BuildArtifact(bin_path, out_dir, temporary_directory)

    try:
        transpile = [*btrcpy_cmd, program, "--debug", "--no-cache", "-o", c_path]
        _run(transpile, "transpile", cwd=cwd)

        compile_cmd = [cc, "-g", "-O0", "-std=c11", c_path, "-o", bin_path, "-lm", "-lpthread", *(cflags or [])]
        _run(compile_cmd, "C compile", cwd=cwd)
    except Exception:
        artifact.cleanup()
        raise
    return artifact


def _run(cmd, phase, cwd=None):
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            **_process_group_options(),
        )
        stdout, stderr = proc.communicate(timeout=_BUILD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        if proc is not None:
            _terminate_process_group(proc)
            _reap_process(proc)
        raise BuildError(f"{phase} timed out after {_BUILD_TIMEOUT_SECONDS} seconds") from error
    except OSError as error:
        if proc is not None:
            _terminate_process_group(proc)
            _reap_process(proc)
        raise BuildError(f"{phase} failed: {error}") from error
    if proc.returncode != 0:
        out = (stderr or "") + (stdout or "")
        raise BuildError(f"{phase} failed:\n{out.strip()}")


def _process_group_options() -> dict:
    """Launch each build as an owned process group for timeout cleanup."""
    if _IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_process_group(proc) -> None:
    """Force-stop a timed-out builder and every descendant in its group."""
    if _IS_WINDOWS:
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_TERMINATION_TIMEOUT_SECONDS,
            )
    else:
        with suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    if proc.poll() is None:
        with suppress(OSError):
            proc.kill()


def _reap_process(proc) -> None:
    """Bound output-pipe draining even if platform tree cleanup is partial."""
    try:
        proc.communicate(timeout=_TERMINATION_TIMEOUT_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            with suppress(OSError):
                stream.close()
    with suppress(OSError, subprocess.TimeoutExpired):
        proc.wait(timeout=_TERMINATION_TIMEOUT_SECONDS)
