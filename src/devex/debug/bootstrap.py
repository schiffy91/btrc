"""Ensure the ``lldb`` Python module is importable, re-exec'ing if needed.

The lldb module only imports under the specific interpreter lldb was built
against (on macOS, Apple's ``/usr/bin/python3``). VSCode may launch this adapter
with any python, so on import failure we locate lldb's module dir via
``lldb -P`` and re-exec under an interpreter that can load it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

_GUARD = "BTRC_DAP_BOOTSTRAPPED"


def _can_run_adapter(python: str, env: dict[str, str]) -> bool:
    try:
        probe = subprocess.run(
            [python, "-c", "import lldb; import adapter"],
            env=env,
            capture_output=True,
        )
    except OSError:
        return False
    return probe.returncode == 0


def ensure_lldb() -> None:
    try:
        import lldb  # noqa: F401

        return
    except ImportError:
        pass

    if os.environ.get(_GUARD):
        sys.stderr.write(
            "btrc debug adapter: the lldb Python module is unavailable under "
            f"{sys.executable}. Install Xcode/llvm command-line tools.\n"
        )
        sys.exit(1)

    lldb_exe = shutil.which("lldb") or "/usr/bin/lldb"
    try:
        pypath = subprocess.check_output([lldb_exe, "-P"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        sys.stderr.write(f"btrc debug adapter: cannot locate lldb ({error}).\n")
        sys.exit(1)

    script = os.path.abspath(sys.argv[0])
    script_dir = os.path.dirname(script)
    for py in ("/usr/bin/python3", shutil.which("python3"), sys.executable):
        if not py:
            continue
        env = dict(os.environ)
        env[_GUARD] = "1"
        env["PYTHONPATH"] = os.pathsep.join(p for p in (pypath, script_dir, env.get("PYTHONPATH", "")) if p)
        if _can_run_adapter(py, env):
            os.execve(py, [py, script, *sys.argv[1:]], env)

    sys.stderr.write("btrc debug adapter: no Python interpreter could import both lldb and the adapter.\n")
    sys.exit(1)
