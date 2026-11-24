"""Run the unchanged public native window example, editing its title in a GTK-free root."""

import os
import re
import shlex
import subprocess
import sys
import time

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


@pytest.fixture(scope="module", params=["python", "selfhost"])
def edit_app(request, tmp_path_factory):
    work = tmp_path_factory.mktemp("public-field")
    return build_app(request.param, ROOT / "examples/gui/Native.btrc", work, request)


@pytest.fixture(scope="module")
def edit_devices(tmp_path_factory):
    work = tmp_path_factory.mktemp("edit-drivers")
    driver = work / "driver"
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
    method = work / "input-method"
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", NATIVE / "WaylandInputMethod.c", *flags, "-o", method],
        check=True,
    )
    return driver, method


def test_normal_example_edits_its_window(edit_app, edit_devices, tmp_path):
    driver, _ = edit_devices
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, edit_app, driver, tmp_path], check=True, timeout=50
    )


def test_input_method_updates_the_public_field(edit_app, edit_devices, tmp_path):
    driver, method = edit_devices
    result = subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "ime", edit_app, driver, method, tmp_path], timeout=50
    )
    if result.returncode == 77:
        pytest.skip("the test compositor does not advertise an input method manager")
    assert result.returncode == 0


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_switch_from_input_method_to_keyboard_menu(frontend, edit_devices, tmp_path, request):
    app = build_app(frontend, NATIVE / "WaylandFieldMenu.btrc", tmp_path, request)
    driver, method = edit_devices
    result = subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "ime-menu", app, driver, method, tmp_path], timeout=50
    )
    if result.returncode == 77:
        pytest.skip("the test compositor does not advertise an input method manager")
    assert result.returncode == 0


def test_editing_uses_the_shaped_ligature_boundaries(edit_app, edit_devices, tmp_path):
    driver, _ = edit_devices
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "caret", edit_app, driver, tmp_path],
        check=True,
        timeout=40,
    )


def point_inside_ligature(program, driver, folder):
    # Noto Sans at 13px puts the first f caret of "office" at 12.095px
    # inside the ffi cluster. The click ten pixels after the pen is closer
    # to the preceding caret at 8px. Reshaping the prefix would insert after f.
    with subprocess.Popen([driver, "caret"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as pointer:
        try:
            assert pointer.stdout.readline().strip() == "keyboard ready"
            with subprocess.Popen(empty_root_command(program, folder)) as app:
                try:
                    assert pointer.stdout.readline().strip() == "ligature ready"
                    shot = subprocess.check_output(["grim", "-t", "ppm", "-"])
                    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", shot)
                    assert header
                    width = int(header[1])
                    pixels = shot[header.end() :]
                    border = bytes((65, 138, 223))
                    first = pixels.find(border * 120)
                    assert first >= 0 and first % 3 == 0
                    top, left = divmod(first // 3, width)
                    pointer.stdin.write(f"{left + 8 + 10} {top + 10}\n")
                    pointer.stdin.flush()
                    assert pointer.wait(timeout=10) == 0
                    assert app.wait(timeout=7) == 0
                finally:
                    if app.poll() is None:
                        app.kill()
        finally:
            if pointer.poll() is None:
                pointer.kill()


def exercise(program, driver, folder):
    with subprocess.Popen(empty_root_command(program, folder)) as app:
        try:
            subprocess.run([driver], check=True, timeout=20)
            assert app.wait(timeout=7) == 0
        finally:
            if app.poll() is None:
                app.kill()


def input_method(program, driver, method, folder, *, menu=False):
    def send(process):
        process.stdin.write("\n")
        process.stdin.flush()

    def screen():
        return subprocess.check_output(["grim", "-t", "ppm", "-"])

    with (
        subprocess.Popen([method, "field"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as ime,
        subprocess.Popen(
            [driver, "ime-menu" if menu else "ime"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        ) as keys,
    ):
        try:
            state = ime.stdout.readline().strip()
            if state == "IM unavailable":
                sys.exit(77)
            assert state == "IM ready" and keys.stdout.readline().strip() == "keyboard ready"
            with subprocess.Popen(empty_root_command(program, folder)) as app:
                try:
                    assert keys.stdout.readline().strip() == "field focused"
                    assert ime.stdout.readline().strip() == "surrounding confirmed"
                    before = screen()
                    send(ime)
                    assert ime.stdout.readline().strip() == "preedit sent"
                    deadline = time.monotonic() + 6
                    while screen() == before:
                        assert time.monotonic() < deadline, "preedit glyphs did not appear"
                    send(ime)
                    assert ime.stdout.readline().strip() == "committed text confirmed"
                    assert ime.wait(timeout=3) == 0
                    send(keys)
                    assert keys.wait(timeout=10) == 0 and app.wait(timeout=6) == 0
                finally:
                    if app.poll() is None:
                        app.kill()
        finally:
            for process in (keys, ime):
                if process.poll() is None:
                    process.kill()


if __name__ == "__main__":
    if sys.argv[1] == "caret":
        point_inside_ligature(*sys.argv[2:])
    elif sys.argv[1] in ("ime", "ime-menu"):
        input_method(*sys.argv[2:], menu=sys.argv[1] == "ime-menu")
    else:
        exercise(*sys.argv[1:])
