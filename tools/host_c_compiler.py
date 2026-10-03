"""Which host C compiler builds generated C when nothing names one.

The test suites (through ``src.tests.c_toolchains``) and ``tools.bench`` share
this one answer. It imports nothing beyond the standard library, so a tool can
use it in a shell without pytest.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys


class HostCCompiler:
    """The host C compiler selection: ``BTRC_CC`` when set, else the platform default."""

    @staticmethod
    def default() -> str:
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

    @classmethod
    def default_cxx(cls) -> str:
        """The C++ driver from the same toolchain as ``default()``: clang++
        beside clang, else the platform's ``c++``. Pairing clang with a GCC
        ``c++`` would link one toolchain's objects with the other's runtime."""
        return "clang++" if cls.default() == "clang" else "c++"

    @classmethod
    def configured(cls, *, empty_is_unset: bool = False) -> list[str]:
        """The C compiler command: ``BTRC_CC`` when set, else ``default()``.

        An empty ``BTRC_CC`` is an error unless `empty_is_unset`, which a tool
        that only needs a default passes.
        """
        configured = os.environ.get("BTRC_CC")
        if configured is None or (empty_is_unset and not configured):
            configured = cls.default()
        command = shlex.split(configured)
        if not command:
            raise ValueError("BTRC_CC must name a C compiler")
        return command
