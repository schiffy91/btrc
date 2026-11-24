"""Run the unchanged public native window example, editing its title in a GTK-free root."""

import os
import shlex
import subprocess
import sys

import pytest

from src.tests.python.test_first_party_wayland_window import NATIVE, PROBE, ROOT, SESSION
from src.tests.python.test_wayland_public_preview import build_app, empty_root_command


def test_unicode_edit_transactions(tmp_path):
    sources = ROOT / "src/stdlib/GUI"
    output = tmp_path / "edit"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
            NATIVE / "WaylandEditBuffer.c",
            sources / "Linux/Wayland/EditBuffer.c",
            sources / "Text/Grapheme.c",
            "-o",
            output,
        ],
        check=True,
    )
    subprocess.run([output], env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1"}, check=True)


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_normal_example_edits_its_window(frontend, tmp_path, request):
    executable = build_app(frontend, ROOT / "examples/gui/Native.btrc", tmp_path, request)
    driver = tmp_path / "driver"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True))
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            NATIVE / "WaylandEditDriver.c",
            PROBE / "WaylandInput.c",
            *sorted((PROBE / "wayland").glob("*-protocol.c")),
            *flags,
            "-o",
            driver,
        ],
        check=True,
    )
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, executable, driver, tmp_path], check=True, timeout=50
    )


def exercise(program, driver, folder):
    with subprocess.Popen(empty_root_command(program, folder)) as app:
        try:
            subprocess.run([driver], check=True, timeout=20)
            assert app.wait(timeout=7) == 0
        finally:
            if app.poll() is None:
                app.kill()


if __name__ == "__main__":
    exercise(*sys.argv[1:])
