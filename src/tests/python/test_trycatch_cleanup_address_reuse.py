"""Regression for cleanup-slot freezing before managed destruction."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
FIXTURE = Path(__file__).with_name("fixtures") / "trycatch_cleanup_address_reuse.c"
ROOTS = {
    "__btrc_register_cleanup",
    "__btrc_run_cleanups",
    "__btrc_mark_destroyed",
    "__btrc_try_state_cleanup",
    "__btrc_cycle_state_cleanup",
}
HEADERS = """\
#include <limits.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
"""

pytestmark = pytest.mark.skipif(
    not COMPILERS or sys.platform == "win32",
    reason="requires a hosted strict C11 compiler",
)


def _compiler_environment(compiler: str) -> dict[str, str] | None:
    if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
        return None
    environment = {
        name: os.environ[name]
        for name in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        if name in os.environ
    }
    environment.update({"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": "/tmp"})
    return environment


def _runtime_source() -> str:
    helpers = "\n\n".join(helper.c_source for helper in helper_decls_for_roots(ROOTS))
    return f"{HEADERS}\n{helpers}\n\n{FIXTURE.read_text()}\n"


@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cleanup_batch_freezes_values_before_first_destroy(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = tmp_path / "trycatch_cleanup_address_reuse.c"
    binary = tmp_path / "trycatch_cleanup_address_reuse"
    source.write_text(_runtime_source())
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-function",
            "-O2",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(binary),
        ],
        env=_compiler_environment(c_compiler),
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run(
        [str(binary)],
        env=_compiler_environment(c_compiler),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert executed.returncode == 0, (
        executed.returncode,
        executed.stdout,
        executed.stderr,
    )
