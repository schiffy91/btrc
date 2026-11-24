"""Exercise compositor-compiled keyboard layouts and the public field in an empty client root."""

import os
import shlex
import subprocess
import sys

import pytest

from src.tests.python.test_first_party_wayland_window import NATIVE, PROBE, PROVIDER, SESSION, wayland_session_env
from src.tests.python.test_wayland_public_preview import empty_root_command
from src.tests.python.test_wayland_public_text_field import edit_app  # noqa: F401


@pytest.fixture(scope="module")
def layout_tools(tmp_path_factory):
    folder = tmp_path_factory.mktemp("physical-keyboard")
    package = subprocess.run(["pkg-config", "--cflags", "--libs", "xkbcommon"], capture_output=True, text=True)
    if package.returncode:
        pytest.skip("the independent physical keyboard oracle requires the host xkbcommon SDK")
    common = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror"]
    oracle = folder / "oracle"
    subprocess.run(
        [
            *common,
            "-pedantic-errors",
            f"-I{PROVIDER}",
            NATIVE / "WaylandLayoutOracle.c",
            PROVIDER / "Keymap.c",
            *shlex.split(package.stdout),
            "-o",
            oracle,
        ],
        check=True,
    )
    driver = folder / "driver"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True))
    subprocess.run(
        [
            *common,
            NATIVE / "WaylandLayoutDriver.c",
            PROBE / "WaylandInput.c",
            *sorted((PROBE / "wayland").glob("*-protocol.c")),
            *flags,
            "-o",
            driver,
        ],
        check=True,
    )
    return oracle, driver


@pytest.mark.parametrize(
    "layout,mode",
    [
        ("us", "all"),
        ("us", "relocate"),
        *((layout, "all") for layout in ("ru", "ara", "il", "am", "th", "bg", "vn")),
        *((layout, "unicode") for layout in ("de", "fr", "es", "gr", "lt", "az")),
    ],
)
def test_compiled_keyboard(layout_tools, tmp_path, layout, mode):
    oracle, _ = layout_tools
    subprocess.run([oracle, layout, mode, tmp_path / "keymap"], check=True, timeout=15)


def test_public_field_uses_physical_keypad(layout_tools, edit_app, tmp_path):  # noqa: F811
    oracle, driver = layout_tools
    keymap = tmp_path / "keymap"
    subprocess.run([oracle, "us", "all", keymap], check=True)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, edit_app, driver, keymap, tmp_path],
        env=wayland_session_env(),
        check=True,
        timeout=40,
    )


@pytest.mark.parametrize(
    "layout,title", [("gr", "αΣδ"), ("ru", "фЫв"), ("ara", "شٍي"), ("il", "שSג"), ("am", "ջՎգ"), ("th", "ฟฆก")]
)
def test_public_field_accepts_named_symbols(layout_tools, edit_app, tmp_path, layout, title):  # noqa: F811
    oracle, driver = layout_tools
    keymap = tmp_path / "keymap"
    subprocess.run([oracle, layout, "unicode", keymap], check=True)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, edit_app, driver, keymap, tmp_path, title],
        env=wayland_session_env(),
        check=True,
        timeout=40,
    )


if __name__ == "__main__":
    _, app, driver, keymap, folder, *title = sys.argv
    assert not os.environ.get("DISPLAY")
    with subprocess.Popen(empty_root_command(app, folder)) as program:
        try:
            subprocess.run([driver, keymap, *title], check=True, timeout=20)
            assert program.wait(timeout=7) == 0
        finally:
            if program.poll() is None:
                program.kill()
