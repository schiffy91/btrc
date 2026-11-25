"""Regular expressions, fnmatch and glob match on Windows as on Linux and macOS.

The MinGW-w64 overlay supplies first-party C11 implementations of POSIX regex,
shell patterns and globbing (src/runtime/windows/README.md). The overlay's
regex.h, fnmatch.h and glob.h declare the POSIX interfaces and compile the
engine into each unit with internal linkage, so the hosted-ABI names are
available on the gnu Windows rows and Library.Regex, Library.Pattern and
glob(3) programs build there unchanged. This module proves the matching:

- PosixMatching.c, a fixed table of regcomp/regexec and fnmatch cases, prints
  identical lines built against the host C library (glibc, or macOS's libc)
  and against the Windows overlay compiled for the host.
- PosixRegexSemantics.c verifies IEEE Std 1003.1 leftmost-longest submatch
  disambiguation, BRE backreferences, all regcomp error codes, regerror sizing
  and ReDoS time bounds on the host and cross-built for Windows.
- The same programs, and the regex, fnmatch and glob corpus programs through
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
from src.tests.dependencies import DependencyAudit
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


def _build_host(output: Path, include: Path | None = None, driver: Path = DRIVER) -> Path:
    """Build a parity driver for this host against its C library or, with
    `include`, against the first-party Windows overlay under strict C11."""
    compiler = host_c_compiler()
    if compiler is None or sys.platform == "win32":
        pytest.skip("requires a POSIX host C compiler and C library")
    command = [*compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE"]
    if include is not None:
        command += ["-I", str(include)]
    built = subprocess.run(
        [*command, str(driver), "-o", str(output)],
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


def test_first_party_engine_matches_the_host_library(host_library_output, tmp_path):
    """The byte-oriented Windows overlay answers the shared cases as the host C library does."""
    shim = tmp_path / "include"
    shim.mkdir()
    for header in ("regex.h", "fnmatch.h"):
        (shim / header).write_text(f'#include "{OVERLAY / header}"\n', encoding="utf-8")
    overlay = _run(_build_host(tmp_path / "overlay", include=shim))
    difference = difflib.unified_diff(
        host_library_output.splitlines(), overlay.splitlines(), "host library", "first-party overlay", lineterm=""
    )
    assert overlay == host_library_output, "\n".join(difference)


def test_regex_recovers_from_workspace_allocation_failure(tmp_path):
    shim = tmp_path / "include"
    shim.mkdir()
    (shim / "regex.h").write_text(f'#include "{OVERLAY / "regex.h"}"\n', encoding="utf-8")
    driver = DRIVER.with_name("RegexDispatchRecovery.c")
    assert _run(_build_host(tmp_path / "recovery", shim, driver)) == ""


def test_first_party_regex_posix_semantics_and_redos(tmp_path):
    shim = tmp_path / "include"
    shim.mkdir()
    (shim / "regex.h").write_text(f'#include "{OVERLAY / "regex.h"}"\n', encoding="utf-8")
    driver = DRIVER.with_name("PosixRegexSemantics.c")
    assert _run(_build_host(tmp_path / "semantics", shim, driver)) == "posix-regex-semantics ok\n"


def test_generated_shell_patterns_match_the_host_library(tmp_path):
    shim = tmp_path / "include"
    shim.mkdir()
    (shim / "fnmatch.h").write_text(f'#include "{OVERLAY / "fnmatch.h"}"\n', encoding="utf-8")
    driver = DRIVER.with_name("GeneratedShellPatterns.c")
    host = _run(_build_host(tmp_path / "libc", driver=driver)).splitlines()
    overlay = _run(_build_host(tmp_path / "overlay", include=shim, driver=driver)).splitlines()
    assert len(host) == len(overlay) == 11**3
    for row, (expected, actual) in enumerate(zip(host, overlay, strict=True)):
        assert actual == expected, f"generated shell pattern {row}"


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
def test_windows_matching_driver_builds_strictly(host_library_output, target, tmp_path):
    executable = build_c_fixture([DRIVER], target, tmp_path / "posix-matching.exe")
    assert not DependencyAudit().binary_problems(executable, target)
    publish(executable, f"posix-matching-{target}", host_library_output.encode())


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
def test_windows_regex_semantics_builds_strictly(target, tmp_path):
    executable = build_c_fixture([DRIVER.with_name("PosixRegexSemantics.c")], target, tmp_path / "posix-semantics.exe")
    assert not DependencyAudit().binary_problems(executable, target)
    publish(executable, f"posix-regex-semantics-{target}", b"posix-regex-semantics ok\n")


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("source", PROGRAMS)
def test_matching_corpus_builds_for_windows(source, frontend, target, request, tmp_path):
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    executable = build_corpus_program(source, frontend, target, btrcc, tmp_path)
    assert not DependencyAudit().binary_problems(executable, target)
    program = CORPUS / source
    expected = program.parent / "expected"
    stderr = expected / f"{program.stem}.stderr"
    publish(
        executable,
        f"corpus-{frontend}-{program.stem}-{target}",
        (expected / f"{program.stem}.stdout").read_bytes(),
        stderr.read_bytes() if stderr.is_file() else b"",
    )
