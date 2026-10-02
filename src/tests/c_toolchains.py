"""The host C toolchains every test module compiles generated C with.

One owner answers three questions the suites used to re-derive per module:
which compiler a single-compiler test uses (``configured_c_compiler``, honoring
``BTRC_CC``), which compilers a strict-C11 matrix test sweeps
(``HOST_C_COMPILERS``), and how a test that needs one skips when none exists
(``requires_host_c_compiler``).
"""

from __future__ import annotations

import shutil

import pytest

from tools.host_c_compiler import HostCCompiler

# The selection itself lives in tools.host_c_compiler, which tools.bench shares
# without importing pytest.
default_c_compiler = HostCCompiler.default


def configured_c_compiler() -> list[str]:
    """The C compiler command a single-compiler test runs: ``BTRC_CC`` when set,
    else ``default_c_compiler()``."""
    return HostCCompiler.configured()


# Every GCC and Clang on PATH, in that order: the strict-C11 matrix tests
# compile the same generated C with each.
HOST_C_COMPILERS: tuple[str, ...] = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

requires_host_c_compiler = pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires GCC or Clang")
