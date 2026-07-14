import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WIN = ROOT / "src" / "stdlib" / "win"
NATIVE_TESTS = ROOT / "src" / "tests" / "native"


def test_windows_filesystem_shims_never_follow_reparse_points() -> None:
    source = (WIN / "btrc_win_compat.h").read_text()
    assert "FILE_ATTRIBUTE_REPARSE_POINT" in source
    assert "RemoveDirectoryA(path)" in source
    assert "#define lstat stat" not in source
    assert "btrc_lstat" in source
    assert "btrc_unlink" in source


def test_windows_orphan_header_shims_cover_emitted_stdlib_includes() -> None:
    """Every intentionally orphanable POSIX include must resolve under MinGW."""
    for header in (
        "fnmatch.h",
        "glob.h",
        "grp.h",
        "poll.h",
        "pwd.h",
        "regex.h",
        "termios.h",
        "sys/select.h",
        "sys/socket.h",
        "sys/wait.h",
    ):
        assert (WIN / header).is_file(), header


def test_windows_compat_header_is_safe_across_translation_units(
    tmp_path: Path,
) -> None:
    zig = shutil.which("zig")
    if not zig:
        pytest.skip("zig cross compiler is unavailable")
    executable = tmp_path / "win-compat.exe"
    subprocess.run(
        [
            zig,
            "cc",
            "-target",
            "x86_64-windows-gnu",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(WIN),
            "-include",
            str(WIN / "btrc_win_compat.h"),
            str(NATIVE_TESTS / "win_compat_main.c"),
            str(NATIVE_TESTS / "win_compat_helper.c"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    wine = shutil.which("wine64") or shutil.which("wine")
    if wine:
        subprocess.run([wine, str(executable)], check=True)
