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


def ensure_lldb() -> None:
    try:
        import lldb  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get(_GUARD):
        sys.stderr.write(
            "btrc debug adapter: the lldb Python module is unavailable under "
            f"{sys.executable}. Install Xcode/llvm command-line tools.\n")
        sys.exit(1)

    lldb_exe = shutil.which("lldb") or "/usr/bin/lldb"
    try:
        pypath = subprocess.check_output([lldb_exe, "-P"], text=True,
                                         stderr=subprocess.DEVNULL).strip()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"btrc debug adapter: cannot locate lldb ({e}).\n")
        sys.exit(1)

    script = os.path.abspath(sys.argv[0])
    for py in ("/usr/bin/python3", shutil.which("python3"), sys.executable):
        if not py:
            continue
        env = dict(os.environ)
        env[_GUARD] = "1"
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (pypath, env.get("PYTHONPATH", "")) if p)
        try:
            probe = subprocess.run([py, "-c", "import lldb"], env=env,
                                   capture_output=True)
        except Exception:  # noqa: BLE001
            continue
        if probe.returncode == 0:
            os.execve(py, [py, script, *sys.argv[1:]], env)

    sys.stderr.write(
        "btrc debug adapter: no Python interpreter could import lldb.\n")
    sys.exit(1)
