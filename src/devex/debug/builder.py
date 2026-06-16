"""Build a .btrc program into a debuggable native binary.

Transpiles with ``--debug`` (so the C carries ``#line`` directives back to the
.btrc source) and compiles with ``-g`` so the binary's DWARF references btrc
source — giving lldb native btrc breakpoints and stepping.
"""

from __future__ import annotations

import os
import subprocess


class BuildError(RuntimeError):
    pass


def build(program, *, btrcpy_cmd, cc="cc", out_dir=None, cflags=None, cwd=None):
    """Return the path to a freshly built debug binary for *program*.

    btrcpy_cmd: argv list that runs the btrc compiler (e.g.
        ["python3", "-m", "src.compiler.python.main"] or ["/path/bin/btrcpy"]).
    cwd: working directory for the transpile step — required for the
        ``-m src.compiler.python.main`` form to resolve from a source checkout.
    """
    program = os.path.abspath(program)
    if not os.path.isfile(program):
        raise BuildError(f"program not found: {program}")
    out_dir = out_dir or os.path.join(os.path.dirname(program), ".btrc-debug")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(program))[0]
    c_path = os.path.join(out_dir, stem + ".c")
    bin_path = os.path.join(out_dir, stem)

    transpile = [*btrcpy_cmd, program, "--debug", "--no-cache", "-o", c_path]
    _run(transpile, "transpile", cwd=cwd)

    compile_cmd = [cc, "-g", "-O0", "-std=c11", c_path, "-o", bin_path,
                   "-lm", "-lpthread", *(cflags or [])]
    _run(compile_cmd, "C compile", cwd=cwd)
    return bin_path


def _run(cmd, phase, cwd=None):
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        out = (proc.stderr or "") + (proc.stdout or "")
        raise BuildError(f"{phase} failed:\n{out.strip()}")
