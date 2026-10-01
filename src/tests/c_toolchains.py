"""The host C toolchains every test module compiles generated C with.

One owner answers three questions the suites used to re-derive per module:
which compiler a single-compiler test uses (``configured_c_compiler``, honoring
``BTRC_CC``), which compilers a strict-C11 matrix test sweeps
(``HOST_C_COMPILERS``), and how a test that needs one skips when none exists
(``requires_host_c_compiler``).
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys

import pytest


def default_c_compiler() -> str:
    """The host C compiler when BTRC_CC is unset.

    Nix's `cc` on macOS is GCC, which emulates thread-local storage through
    pthread keys, so every compiled btrc program pays a call per access where
    Apple's clang reads a native TLV descriptor. Measured on one identical
    generated btrcc.c, a cold BTRSmith compile takes 74.9 s from the GCC build
    against 62.3 s from the clang build: GCC's takes 20% longer over the whole
    compile, and 79% longer on the generic-instance closure, the phase densest in thread-local and ARC
    traffic.
    """
    if sys.platform == "darwin" and shutil.which("clang"):
        return "clang"
    return "cc"


def configured_c_compiler() -> list[str]:
    """The C compiler command a single-compiler test runs: ``BTRC_CC`` when set,
    else ``default_c_compiler()``."""
    command = shlex.split(os.environ.get("BTRC_CC", default_c_compiler()))
    if not command:
        raise ValueError("BTRC_CC must name a C compiler")
    return command


# Every GCC and Clang on PATH, in that order: the strict-C11 matrix tests
# compile the same generated C with each.
HOST_C_COMPILERS: tuple[str, ...] = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

requires_host_c_compiler = pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires GCC or Clang")
