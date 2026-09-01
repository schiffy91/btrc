import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WIN = ROOT / "src" / "stdlib" / "win"
NATIVE_TESTS = ROOT / "src" / "tests" / "native"


def _run_windows_binary(executable: Path) -> None:
    if os.name == "nt":
        subprocess.run([str(executable)], check=True)
        return
    wine = shutil.which("wine64") or shutil.which("wine")
    if wine:
        subprocess.run([wine, str(executable)], check=True)


def test_windows_filesystem_shims_never_follow_reparse_points() -> None:
    source = (WIN / "btrc_win_compat.h").read_text()
    realpath_source = (WIN / "btrc_win_realpath.h").read_text()
    assert "#include <windows.h>" not in source
    assert "#define BTRC_WIN_GET_FILE_ATTRIBUTES GetFileAttributesA" in source
    assert '#include "btrc_win_errors.h"' in source
    assert "FILE_ATTRIBUTE_REPARSE_POINT" in source
    assert "BTRC_WIN_REMOVE_DIRECTORY(path)" in source
    assert "#define lstat stat" not in source
    assert "btrc_lstat" in source
    assert "btrc_unlink" in source
    assert "#define mkdir(path, mode) ((void)(mode), _mkdir(path))" in source
    assert '#include "btrc_win_realpath.h"' in source
    assert "GetFinalPathNameByHandleW" in realpath_source
    assert "CreateFileW" in realpath_source
    assert "MultiByteToWideChar" in realpath_source
    assert "_MAX_PATH" not in realpath_source
    assert "_fullpath" not in realpath_source
    assert "if (!path || resolved)" in realpath_source
    assert "memcpy(resolved" not in realpath_source
    create_file = realpath_source.index("void *file = CreateFileW")
    capture_error = realpath_source.index("unsigned long create_error", create_file)
    free_input = realpath_source.index("free(wide_input)", create_file)
    map_error = realpath_source.index("btrc_win_path_error(create_error)", create_file)
    assert create_file < capture_error < free_input < map_error
    assert "#define O_CLOEXEC _O_NOINHERIT" in source
    assert "flags & (O_DIRECTORY | O_NOFOLLOW)" in source
    assert "errno = ENOTSUP" in source
    assert "btrc_win_popen" in source
    assert "#define popen btrc_win_popen" in source
    assert "btrc_win_pclose" in source
    assert "#define pclose btrc_win_pclose" in source


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
        "sys/resource.h",
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
            str(NATIVE_TESTS / "win_compat_windows_header.c"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    _run_windows_binary(executable)


def test_windows_error_and_open_flag_seams_fail_closed(tmp_path: Path) -> None:
    zig = shutil.which("zig")
    if not zig:
        pytest.skip("zig cross compiler is unavailable")
    executable = tmp_path / "win-compat-error-seam.exe"
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
            "-DBTRC_WIN_GET_LAST_ERROR=btrc_test_get_last_error",
            "-DBTRC_WIN_GET_FILE_ATTRIBUTES=btrc_test_get_file_attributes",
            "-DBTRC_WIN_REMOVE_DIRECTORY=btrc_test_remove_directory",
            "-I",
            str(WIN),
            "-include",
            str(WIN / "btrc_win_compat.h"),
            str(NATIVE_TESTS / "win_compat_error_seam.c"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    _run_windows_binary(executable)
