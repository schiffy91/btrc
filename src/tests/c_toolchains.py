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
import stat
import sys
import time
from collections import deque
from pathlib import Path

import pytest

from tools.host_c_compiler import HostCCompiler

# The selection itself lives in tools.host_c_compiler, which tools.bench shares
# without importing pytest.
default_c_compiler = HostCCompiler.default
default_cxx_compiler = HostCCompiler.default_cxx


def selfhost_link_flags() -> list[str]:
    """Reserve the Darwin compiler's main stack while retaining one OS thread.

    Linux's compiler entry raises its process-local soft limit instead.
    Ordinary generated programs do not require this compiler build policy.
    """
    return ["-Wl,-stack_size,0x20000000"] if sys.platform == "darwin" else []


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


class HostCompilerDiagnostics:
    """Selection and failure-time filesystem facts, never compiler recovery."""

    MAX_COMPONENTS = 128
    MAX_SYMLINKS = 40
    HEADER_BYTES = 4096

    def __init__(self, paths: tuple[str, ...]) -> None:
        self.selected = {path: self.snapshot(path) for path in paths}

    @staticmethod
    def identity(path: str) -> dict:
        try:
            value = os.lstat(path)
            return {
                "mode": value.st_mode,
                "device": value.st_dev,
                "inode": value.st_ino,
                "size": value.st_size,
                "mtime_ns": value.st_mtime_ns,
            }
        except OSError as error:
            return {"error": type(error).__name__, "errno": error.errno}

    @classmethod
    def path_facts(cls, path: str) -> dict:
        """Resolve with explicit component/hop bounds, retaining parent links too."""
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = Path.cwd() / absolute
        pending = deque(absolute.parts[1:])
        resolved = Path(absolute.anchor)
        links = []
        result = {"path": path, "lstat": cls.identity(path), "symlinks": links}
        for _ in range(cls.MAX_COMPONENTS):
            if not pending:
                result["realpath"] = str(resolved)
                result["resolved_lstat"] = cls.identity(str(resolved))
                break
            part = pending.popleft()
            if part == "..":
                resolved = resolved.parent
                continue
            candidate = resolved / part
            value = cls.identity(str(candidate))
            if "error" in value:
                result["unavailable_component"] = {"path": str(candidate), **value}
                break
            if stat.S_ISLNK(value["mode"]):
                if len(links) == cls.MAX_SYMLINKS:
                    result["limit"] = "symlink hops"
                    break
                try:
                    target = os.readlink(candidate)
                except OSError as error:
                    result["link_error"] = {"path": str(candidate), "errno": error.errno}
                    break
                links.append({"path": str(candidate), "target": target, "lstat": value})
                target_path = Path(target)
                if target_path.is_absolute():
                    resolved = Path(target_path.anchor)
                    parts = target_path.parts[1:]
                else:
                    parts = target_path.parts
                pending.extendleft(reversed(parts))
            else:
                resolved = candidate
        else:
            result["limit"] = "path components"
        stores = {}
        for candidate in [str(absolute), result.get("realpath", ""), *[row["target"] for row in links]]:
            parts = Path(candidate).parts
            if parts[:3] == ("/", "nix", "store") and len(parts) >= 4:
                store = str(Path(*parts[:4]))
                stores[store] = cls.identity(store)
        result["nix_store_ancestors"] = stores
        return result

    @classmethod
    def snapshot(cls, path: str) -> dict:
        result = {"path": path, "observed_ns": time.time_ns()}
        try:
            result.update(cls.path_facts(path))
            value = result.get("resolved_lstat", {})
            if not stat.S_ISREG(value.get("mode", 0)):
                result["header"] = "not a resolved regular file"
                return result
            # Nonblocking open plus fstat avoids reading a FIFO swapped in after
            # the path inspection. Never dump executable contents or shell args.
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    result["header"] = "opened file is not regular"
                    return result
                result["opened_identity"] = {"device": opened.st_dev, "inode": opened.st_ino}
                header = os.read(descriptor, cls.HEADER_BYTES)
            finally:
                os.close(descriptor)
            if not header.startswith(b"#!"):
                result["header"] = "no shebang"
            elif b"\n" not in header:
                result["header"] = "unterminated or oversized shebang"
            else:
                line = header.split(b"\n", 1)[0][2:].lstrip(b" \t")
                interpreter = line.split(b" ", 1)[0].split(b"\t", 1)[0]
                if not interpreter or b"\0" in interpreter or b"\r" in interpreter:
                    result["header"] = "malformed shebang"
                else:
                    result["header"] = "shebang"
                    result["interpreter"] = cls.path_facts(os.fsdecode(interpreter))
            return result
        except Exception as error:
            # An evidence failure must not hide the original test exception.
            result.update(diagnostic_error=type(error).__name__, errno=getattr(error, "errno", None))
            return result

    def failure(self, error: BaseException) -> dict | None:
        if not isinstance(error, FileNotFoundError) or not isinstance(error.filename, (str, bytes)):
            return None
        path = os.fsdecode(error.filename)
        if path not in self.selected:
            return None
        return {"selected": self.selected[path], "failure": self.snapshot(path)}


HOST_COMPILER_DIAGNOSTICS = HostCompilerDiagnostics(HOST_C_COMPILERS)

requires_host_c_compiler = pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires GCC or Clang")


def sanitizer_clang() -> str | None:
    """The Clang a sanitizer build uses: Apple's on macOS, else Clang on PATH.

    Nix's clang ships a compiler-rt whose sanitizer runtime deadlocks in dyld
    initialization on macOS; Apple's clang links the working one.
    """
    if sys.platform == "darwin" and os.access("/usr/bin/clang", os.X_OK):
        return "/usr/bin/clang"
    return HOST_CLANG
