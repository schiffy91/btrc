"""Find a host C compiler that builds and links AddressSanitizer, and the environment it needs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import HOST_C_COMPILERS
from src.tests.process_limits import C_COMPILE_TIMEOUT


def asan_environment(compiler: str) -> dict[str, str] | None:
    """Isolate the host Apple toolchain from an enclosing Nix build shell."""
    if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
        return None

    environment = {
        name: os.environ[name]
        for name in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        if name in os.environ
    }
    environment.update(
        {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": "/tmp",
        }
    )
    return environment


def find_asan_compiler(tmp_path: Path) -> str:
    """Return the first compiler that can both build and link ASan here."""
    probe = tmp_path / "asan-probe.c"
    executable = tmp_path / "asan-probe"
    probe.write_text("int main(void) { return 0; }\n")
    failures = []
    candidates = list(HOST_C_COMPILERS)
    if sys.platform == "darwin":
        system_clang = "/usr/bin/clang"
        if os.access(system_clang, os.X_OK):
            candidates.append(system_clang)
    unique_candidates = []
    seen = set()
    for compiler in candidates:
        identity = os.path.realpath(compiler)
        if identity not in seen:
            seen.add(identity)
            unique_candidates.append(compiler)

    for compiler in unique_candidates:
        environment = asan_environment(compiler)
        result = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-fsanitize=address",
                str(probe),
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=C_COMPILE_TIMEOUT,
        )
        name = Path(compiler).name
        if result.returncode != 0:
            failures.append(f"{name}: {result.stderr[:120]}")
            continue
        try:
            probe_run = subprocess.run(
                [str(executable)],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{name}: linked ASan runtime timed out")
            continue
        if probe_run.returncode == 0:
            return compiler
        failures.append(f"{name}: ASan probe exited {probe_run.returncode}: {probe_run.stderr[:120]}")
    pytest.skip("AddressSanitizer unavailable: " + "; ".join(failures))
