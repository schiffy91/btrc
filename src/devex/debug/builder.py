"""Build a .btrc program into a debuggable native binary.

Transpiles with ``--debug`` (so the C carries ``#line`` directives back to the
.btrc source) and compiles with ``-g`` so the binary's DWARF references btrc
source — giving lldb native btrc breakpoints and stepping.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field


class BuildError(RuntimeError):
    pass


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
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    except OSError as error:
        raise BuildError(f"{phase} failed: {error}") from error
    if proc.returncode != 0:
        out = (proc.stderr or "") + (proc.stdout or "")
        raise BuildError(f"{phase} failed:\n{out.strip()}")
