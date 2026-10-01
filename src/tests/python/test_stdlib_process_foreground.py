"""ChildProcess.run(foreground=True) hands a controlling terminal to the child.

The program runs as the session leader of a fresh pseudo-terminal. A child in
a background process group that reads the terminal is stopped by SIGTTIN, so
only a real foreground handoff lets it read; the parent then reads the next
line itself, which it can only do once it has taken the terminal back.
"""

from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
C_COMPILER = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
PROGRAM = r"""
    import Library.Process;

    int main() {
        ExecResult background = ChildProcess.run("/bin/sh", ["-c", "read line; printf 'bg:%s' \"$line\""], stdinMode=CHILD_STDIN_INHERIT, timeoutMilliseconds=1000);
        print(f"BACKGROUND|{background.code}|{background.stdout()}");
        ExecResult foreground = ChildProcess.run("/bin/sh", ["-c", "read line; printf 'fg:%s' \"$line\""], stdinMode=CHILD_STDIN_INHERIT, foreground=true, timeoutMilliseconds=20000);
        print(f"FOREGROUND|{foreground.code}|{foreground.stdout()}");
        char line[64];
        if (fgets(line, 64, stdin) == NULL) {
            print("AFTER|<none>");
            return 1;
        }
        string text = line;
        print(f"AFTER|{text.trim()}");
        return 0;
    }
"""


def _build(tmp_path: Path) -> Path:
    source = tmp_path / "Foreground.btrc"
    generated = tmp_path / "foreground.c"
    executable = tmp_path / "foreground"
    source.write_text(textwrap.dedent(PROGRAM))
    environment = {
        **os.environ,
        "BTRC_HOME": str(ROOT / "src"),
        "BTRC_CACHE_DIR": str(tmp_path / "cache"),
        "PYTHONPATH": str(ROOT),
    }
    transpile = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(source), "-o", str(generated)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert transpile.returncode == 0, transpile.stderr
    build = subprocess.run(
        [
            C_COMPILER,
            "-std=c11",
            "-O1",
            f"-I{ROOT / 'src' / 'stdlib'}",
            str(generated),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert build.returncode == 0, build.stderr
    return executable


def _run_on_terminal(executable: Path) -> tuple[int, str]:
    import pty

    pid, master = pty.fork()
    if pid == 0:
        os.execv(str(executable), [str(executable)])
    os.write(master, b"hello\nafter\n")
    output = bytearray()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], 1.0)
        if not ready:
            continue
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output.extend(chunk)
    else:
        os.kill(pid, 9)
    _, status = os.waitpid(pid, 0)
    os.close(master)
    return os.waitstatus_to_exitcode(status), output.decode("utf-8", "replace")


@pytest.mark.skipif(not sys.platform.startswith(("linux", "darwin")), reason="requires POSIX pseudo-terminals")
@pytest.mark.skipif(C_COMPILER is None, reason="requires a hosted C11 compiler")
def test_foreground_child_owns_the_terminal_and_the_caller_reclaims_it(tmp_path: Path) -> None:
    executable = _build(tmp_path)
    code, output = _run_on_terminal(executable)
    lines = [line.strip() for line in output.splitlines()]

    background = next(line for line in lines if line.startswith("BACKGROUND|"))
    assert background.split("|")[1] != "0", output
    assert "bg:hello" not in output

    assert "FOREGROUND|0|fg:hello" in lines, output
    assert "AFTER|after" in lines, output
    assert code == 0, output
