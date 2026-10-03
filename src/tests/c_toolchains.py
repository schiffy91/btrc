"""The host C toolchains every test module compiles generated C with.

One owner answers the questions the suites used to re-derive per module:
which compiler a single-compiler test uses (``configured_c_compiler``, honoring
``BTRC_CC``, and ``host_c_compiler`` when the test must also skip without it),
which C and C++ pair a native build drives (``default_toolchain``),
which compilers a strict-C11 matrix test sweeps (``HOST_C_COMPILERS``), how a
test that needs one skips when none exists (``requires_host_c_compiler``), and
where a test that deliberately needs Clang or GCC finds it (``HOST_CLANG``,
``HOST_CLANGXX``, ``HOST_GCC``, ``sanitizer_clang``).
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from tools.host_c_compiler import HostCCompiler

# The selection itself lives in tools.host_c_compiler, which tools.bench shares
# without importing pytest.
default_c_compiler = HostCCompiler.default
default_cxx_compiler = HostCCompiler.default_cxx


def configured_c_compiler() -> list[str]:
    """The C compiler command a single-compiler test runs: ``BTRC_CC`` when set,
    else ``default_c_compiler()``."""
    return HostCCompiler.configured()


def host_c_compiler() -> list[str] | None:
    """``configured_c_compiler()`` with its executable resolved on PATH, or
    None when that executable is missing and the test should skip."""
    command = configured_c_compiler()
    executable = shutil.which(command[0])
    return [executable, *command[1:]] if executable else None


def default_toolchain() -> tuple[str, str] | None:
    """``default_c_compiler()`` and its paired ``default_cxx_compiler()``, both
    resolved on PATH, for a native build that drives C and C++ together; None
    when either is missing."""
    cc, cxx = shutil.which(default_c_compiler()), shutil.which(default_cxx_compiler())
    return (cc, cxx) if cc and cxx else None


# Compiler-specific tests (sanitizers, Clang-only flags, GCC diagnostics) name
# the one they need; everything else uses the configured compiler.
HOST_GCC = shutil.which("gcc")
HOST_CLANG = shutil.which("clang")
HOST_CLANGXX = shutil.which("clang++")

# Every GCC and Clang on PATH, in that order: the strict-C11 matrix tests
# compile the same generated C with each.
HOST_C_COMPILERS: tuple[str, ...] = tuple(path for path in (HOST_GCC, HOST_CLANG) if path)

requires_host_c_compiler = pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires GCC or Clang")


def sanitizer_clang() -> str | None:
    """The Clang a sanitizer build uses: Apple's on macOS, else Clang on PATH.

    Nix's clang ships a compiler-rt whose sanitizer runtime deadlocks in dyld
    initialization on macOS; Apple's clang links the working one.
    """
    if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK):
        return "/usr/bin/clang"
    return HOST_CLANG
