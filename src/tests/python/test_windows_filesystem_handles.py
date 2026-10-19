"""The Windows FileSystem provider through both compilers, for x64 and ARM64.

src/stdlib/FileSystem/Windows/ is selected only on windows rows (the package
manifest's provider for FileSystemHandles). Its C is spliced into the program,
not bound, so compiling for a windows row needs zig's MinGW-w64 headers but no
native header reader. This driver compiles
src/tests/native/filesystem_windows/WindowsFileSystemCases.btrc with the
reference compiler and btrcc for windows-x64 and windows-arm64, requires both to
splice the provider's C, and links each with zig under the strict C11 flags.
When BTRC_WIN32_EVIDENCE_DIR is set, each executable is copied there and
windows.yml's win32-native job runs it on a Windows runner of its own
architecture; on Windows itself the test runs it. Elsewhere it proves the
selection, the generated C and the link, not the execution.

It also pins what the provider must leave alone: on every other row the
FileSystem package compiles exactly the POSIX bodies, with no Win32 C. And the
one structure layout the provider cannot take from the headers it includes,
REPARSE_DATA_BUFFER, is checked against MinGW's own declaration.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
CASES = REPO / "src/tests/native/filesystem_windows/WindowsFileSystemCases.btrc"
PROVIDER_C = "src/stdlib/FileSystem/Windows/Win32FileSystem.c"
TARGETS = {"windows-x64": "x86_64", "windows-arm64": "aarch64"}
# Every case the program runs; unc and dacl-denied may report a classified skip
# where the runner denies the administrative share or bypasses access lists.
CASE_NAMES = (
    "long-paths",
    "unc",
    "non-ascii",
    "reparse-points",
    "junction-swap",
    "dacl-denied",
    "lock-processes",
    "interrupted-replace",
    "name-rules",
    "known-folders",
    "handle-count",
)
SKIPPABLE = frozenset({"unc", "dacl-denied"})
PROBE = """import Library.FileSystem;
import Library.FileSystem.FileSystemHandles;

int main() {
	var temporary = FileSystem.createTemporaryDirectory("btrc-probe");
	if (!temporary.ok()) { return 1; }
	print(temporary.value().path());
	return temporary.value().close().ok() ? 0 : 2;
}
"""


def transpile_reference(source: Path, target: str) -> str:
    result = Compiler().compile(
        source.read_text(encoding="utf-8"),
        str(source),
        CompilerOptions(use_cache=False, use_ast_cache=False, target=target),
    )
    assert result.failure is None, result.failure
    assert result.c_source is not None
    return result.c_source


def transpile_selfhost(btrcc: Path, source: Path, target: str) -> str:
    completed = subprocess.run(
        [str(btrcc), "--no-cache", "--target", target, str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def check_output(stdout: str) -> None:
    """The program's report: every case once, ok or a classified skip, then PASS."""

    lines = [line for line in stdout.replace("\r", "").split("\n") if line]
    assert lines and lines[-1] == "PASS: windows filesystem cases", lines
    reported = {}
    for line in lines[:-1]:
        name, _, verdict = line.removeprefix("case=").partition(" ")
        assert line.startswith("case=") and name not in reported, line
        reported[name] = verdict
    assert tuple(reported) == CASE_NAMES, reported
    for name, verdict in reported.items():
        assert verdict == "ok" or (name in SKIPPABLE and verdict.startswith("skipped ")), (name, verdict)


@pytest.fixture(scope="module")
def zig() -> str:
    found = shutil.which("zig")
    if found is None:
        pytest.skip("requires zig, which cross-compiles the windows rows (the dev shell provides it)")
    return found


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_both_frontends_build_the_windows_cases(target, zig, request, tmp_path):
    reference = transpile_reference(CASES, target)
    selfhost = transpile_selfhost(request.getfixturevalue("immutable_btrcc"), CASES, target)
    for frontend, source in (("reference", reference), ("selfhost", selfhost)):
        spliced = source.replace("\\", "/")
        assert f'{PROVIDER_C}"' in spliced and 'src/stdlib/Windows/Win32FileIdentity.c"' in spliced, frontend
        generated = tmp_path / f"{frontend}.c"
        generated.write_text(source, encoding="utf-8")
        executable = tmp_path / f"windows-fs-cases-{frontend}-{target}.exe"
        built = subprocess.run(
            [
                zig,
                "cc",
                "-target",
                f"{TARGETS[target]}-windows-gnu",
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                "-I",
                str(REPO / "src/runtime/windows"),
                "-include",
                str(REPO / "src/runtime/windows/btrc_win_compat.h"),
                str(generated),
                "-o",
                str(executable),
                "-lm",
            ],
            capture_output=True,
            text=True,
            timeout=C_COMPILE_TIMEOUT,
            check=False,
        )
        assert built.returncode == 0, built.stderr
        assert executable.read_bytes()[:2] == b"MZ"
        evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
        if evidence:
            Path(evidence).mkdir(parents=True, exist_ok=True)
            shutil.copy2(executable, Path(evidence) / executable.name)
        if sys.platform == "win32":
            ran = subprocess.run(
                [str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT * 4, check=False
            )
            assert ran.returncode == 0, (ran.stdout, ran.stderr)
            check_output(ran.stdout)


@pytest.mark.parametrize("target", ["linux-x86_64", "macos-aarch64", "ios-aarch64", "android-aarch64"])
def test_other_rows_compile_no_win32_c(target, tmp_path):
    """The provider is selected for windows rows only: elsewhere the package's
    POSIX bodies compile and no Win32 C is spliced in."""

    probe = tmp_path / "Probe.btrc"
    probe.write_text(PROBE, encoding="utf-8")
    source = transpile_reference(probe, target)
    assert "Win32FileSystem.c" not in source and "Win32FileIdentity.c" not in source
    assert "btrcWin" not in source
    assert "openat(" in source and "fdopendir(" in source


@pytest.mark.parametrize("target", ["windows-x86_64", "windows-aarch64", "windows-aarch64-msvc"])
def test_windows_rows_compile_no_posix_handle_bodies(target, tmp_path):
    probe = tmp_path / "Probe.btrc"
    probe.write_text(PROBE, encoding="utf-8")
    source = transpile_reference(probe, target)
    assert f'{PROVIDER_C}"' in source.replace("\\", "/")
    for posix in ("openat(", "fdopendir(", "fstatat(", "unlinkat(", "flock("):
        assert posix not in source, posix


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_the_reparse_buffer_offsets_are_the_sdk_layout(target, zig, tmp_path):
    """The provider reads REPARSE_DATA_BUFFER through named byte offsets, since
    the user-mode headers it includes omit the structure. Each offset must be
    offsetof over the structure MinGW declares in ntdef.h, on each architecture."""

    provider = (REPO / PROVIDER_C).read_text(encoding="utf-8")
    offsets = dict(re.findall(r"^#define (BTRC_WIN_REPARSE_\w+) (\d+)$", provider, re.MULTILINE))
    fields = {
        "BTRC_WIN_REPARSE_NAME_FIELDS": "SymbolicLinkReparseBuffer.SubstituteNameOffset",
        "BTRC_WIN_REPARSE_SYMLINK_PATH": "SymbolicLinkReparseBuffer.PathBuffer",
        "BTRC_WIN_REPARSE_MOUNT_POINT_PATH": "MountPointReparseBuffer.PathBuffer",
    }
    assert set(offsets) == set(fields), offsets
    checks = "\n".join(
        f'_Static_assert(offsetof(REPARSE_DATA_BUFFER, {field}) == {offsets[name]}, "{name}");'
        for name, field in fields.items()
    )
    layout = tmp_path / "layout.c"
    layout.write_text(
        "#include <stddef.h>\n#include <ntdef.h>\n"
        "_Static_assert(offsetof(REPARSE_DATA_BUFFER, MountPointReparseBuffer.SubstituteNameOffset) == "
        'offsetof(REPARSE_DATA_BUFFER, SymbolicLinkReparseBuffer.SubstituteNameOffset), "shared name fields");\n'
        f"{checks}\nint main(void) {{ return 0; }}\n",
        encoding="utf-8",
    )
    built = subprocess.run(
        [zig, "cc", "-target", f"{TARGETS[target]}-windows-gnu", "-std=c11", "-pedantic-errors", "-Wall", "-Werror"]
        + ["-c", str(layout), "-o", str(tmp_path / "layout.o")],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
        check=False,
    )
    assert built.returncode == 0, built.stderr


def test_the_report_checker_accepts_only_complete_reports():
    good = "\n".join([*(f"case={name} ok" for name in CASE_NAMES), "PASS: windows filesystem cases"])
    check_output(good)
    check_output(good.replace("case=unc ok", "case=unc skipped access-denied"))
    for broken in (
        good.replace("case=long-paths ok", "case=long-paths skipped no"),
        good.replace("case=handle-count ok\n", ""),
        good.replace("PASS: windows filesystem cases", ""),
    ):
        with pytest.raises(AssertionError):
            check_output(broken)
