import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TRAY = ROOT / "src" / "stdlib" / "tray"
HARNESS = ROOT / "src" / "tests" / "native" / "tray_linux_wire.c"


def test_macos_tray_backend_is_strict_objc(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("macOS Cocoa backend")
    clang = shutil.which("clang")
    if not clang:
        pytest.skip("clang is unavailable")
    subprocess.run(
        [
            clang,
            "-std=c11",
            "-fobjc-arc",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-deprecated-declarations",
            f"-I{TRAY}",
            "-c",
            str(TRAY / "btrc_tray_macos.m"),
            "-o",
            str(tmp_path / "tray-macos.o"),
        ],
        check=True,
    )


def test_linux_tray_dbus_wire_contract(tmp_path: Path) -> None:
    pkg_config = shutil.which("pkg-config")
    if not pkg_config:
        pytest.skip("pkg-config is unavailable")
    flags = subprocess.run(
        [pkg_config, "--cflags", "--libs", "dbus-1"],
        capture_output=True,
        check=False,
        text=True,
    )
    if flags.returncode != 0:
        pytest.skip("libdbus development files are unavailable")

    executable = tmp_path / "tray-wire"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{TRAY}",
            str(HARNESS),
            *flags.stdout.split(),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)
