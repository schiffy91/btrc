"""Regular expressions, fnmatch and glob match on Windows as on Linux and macOS.

MinGW-w64 has no regex, fnmatch or glob, so the Windows overlay vendors
musl 1.2.5's (PLAN.md D22; src/runtime/windows/README.md). The overlay's
regex.h, fnmatch.h and glob.h declare the POSIX interfaces and compile the
engine into each unit, so the hosted-ABI names are available on the gnu
Windows rows and Library.Regex, Library.Pattern and glob(3) programs build
there unchanged. This module proves the matching is the same:

- PosixMatching.c, a fixed table of regcomp/regexec and fnmatch cases, prints
  identical lines built against the host C library (glibc, or macOS's libc)
  and against the vendored engine compiled for the host.
- The same program, and the regex, fnmatch and glob corpus programs through
  both compilers, cross-build for windows-x64 and windows-arm64 under the
  strict flags every Windows unit gets, and are published with the output
  each must print (the host library's, and the corpus goldens): windows.yml's
  win32-native job runs them on Windows x64 and ARM64 and compares.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT
from src.tests.python.windows_evidence_fixtures import (
    OVERLAY,
    WINDOWS_TARGETS,
    build_c_fixture,
    build_corpus_program,
    publish,
)

REPO = Path(__file__).resolve().parents[3]
DRIVER = REPO / "src" / "tests" / "native" / "posix_matching" / "PosixMatching.c"
CORPUS = REPO / "src" / "tests"
PROGRAMS = ("strings/Regex.btrc", "strings/RegexSafety.btrc", "stdlib/PatternAny.btrc", "stdlib/Glob.btrc")


def _run(executable: Path) -> str:
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=True)
    return ran.stdout


def _build_host(output: Path, include: Path | None = None) -> Path:
    """The parity driver for this host, against its C library or, with
    `include`, against the vendored engine. The engine's warning policy is the
    Windows units' (zig's clang under -Werror, checked by the Windows builds
    below and test_windows_posix_overlay.py), not the host compiler's."""
    compiler = host_c_compiler()
    if compiler is None or sys.platform == "win32":
        pytest.skip("requires a POSIX host C compiler and C library")
    # The feature macro btrc's own prologue defines: glibc declares the
    # engine's strnlen only with it, MinGW-w64 unconditionally.
    command = [*compiler, "-std=c11", "-O2", "-D_DEFAULT_SOURCE"]
    if include is None:
        command += ["-Wall", "-Wextra", "-Werror"]
    else:
        command += ["-I", str(include)]
    built = subprocess.run(
        [*command, str(DRIVER), "-o", str(output)],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    return output


@pytest.fixture(scope="module")
def host_library_output(tmp_path_factory) -> str:
    """PosixMatching's output against the host C library: the reference result."""
    output = _run(_build_host(tmp_path_factory.mktemp("posix-matching") / "host-library"))
    assert output.endswith(f"posix-matching cases={output.count(chr(10)) - 1}\n")
    return output


def test_vendored_engine_matches_the_host_library(host_library_output, tmp_path):
    """The overlay's musl engine, built for this host, answers every case as its C library does."""
    shim = tmp_path / "include"
    shim.mkdir()
    for header in ("regex.h", "fnmatch.h"):
        (shim / header).write_text(f'#include "{OVERLAY / header}"\n', encoding="utf-8")
    vendored = _run(_build_host(tmp_path / "vendored", include=shim))
    difference = difflib.unified_diff(
        host_library_output.splitlines(), vendored.splitlines(), "host library", "vendored engine", lineterm=""
    )
    assert vendored == host_library_output, "\n".join(difference)


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
def test_windows_matching_driver_builds_strictly(host_library_output, target, tmp_path):
    executable = build_c_fixture([DRIVER], target, tmp_path / "posix-matching.exe")
    publish(executable, f"posix-matching-{target}", host_library_output.encode())


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("source", PROGRAMS)
def test_matching_corpus_builds_for_windows(source, frontend, target, request, tmp_path):
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    executable = build_corpus_program(source, frontend, target, btrcc, tmp_path)
    program = CORPUS / source
    expected = program.parent / "expected"
    stderr = expected / f"{program.stem}.stderr"
    publish(
        executable,
        f"corpus-{frontend}-{program.stem}-{target}",
        (expected / f"{program.stem}.stdout").read_bytes(),
        stderr.read_bytes() if stderr.is_file() else b"",
    )
