"""Mount and click a public Library.GUI application on a real compositor in an empty runtime root."""

import ctypes.util
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import require_linux_reader
from src.tests.python.test_first_party_wayland_window import (
    ROOT,
    SESSION,
    client,  # noqa: F401
    connected_mouse,
    input_device,  # noqa: F401
)

SAMPLE = ROOT / "examples/gui/Wayland.btrc"
SDK_PACKAGES = {"gtk4", "gtk4-wayland", "gtk4-x11", "wayland-client", "x11", "webkitgtk-6.0"}
RUNTIME_FORBIDDEN = ("libgtk", "libgdk", "libX11", "libwayland", "libfontconfig", "libfreetype", "libpango")


def build_app(frontend, source, tmp_path, request, *, timeout=600):
    require_linux_reader()
    for tool in ("bwrap", "fc-match"):
        if not shutil.which(tool):
            pytest.skip(f"the real GUI/empty-root observer needs {tool}")
    sdk = subprocess.run(["pkg-config", "--path", "wgpu-native"], capture_output=True, text=True)
    if sdk.returncode:
        pytest.skip("the public GPU interface needs the wgpu-native SDK")
    packages = tmp_path / "packages"
    packages.mkdir()
    shutil.copyfile(sdk.stdout.strip(), packages / "wgpu-native.pc")
    env = {**os.environ, "PKG_CONFIG_PATH": "", "PKG_CONFIG_LIBDIR": str(packages)}
    for package in SDK_PACKAGES:
        assert subprocess.run(["pkg-config", "--exists", package], env=env).returncode != 0
    executable = tmp_path / "wayland"
    compiler = "python" if frontend == "python" else str(request.getfixturevalue("immutable_btrcc"))
    subprocess.run(
        [sys.executable, "-m", "tools.ui.build_wayland_preview", "--compiler", compiler, source, "-o", executable],
        cwd=ROOT,
        env=env,
        check=True,
        timeout=timeout,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.qualification.dependencies",
            "binary",
            "--target",
            f"linux-{platform.machine()}",
            executable,
        ],
        cwd=ROOT,
        check=True,
    )
    return executable


@pytest.fixture(scope="module", params=["python", "selfhost"])
def preview_app(request, tmp_path_factory):
    return build_app(request.param, SAMPLE, tmp_path_factory.mktemp("native-wayland-" + request.param), request)


def test_preview(preview_app, input_device, tmp_path):  # noqa: F811
    if not shutil.which("grim"):
        pytest.skip("observing the window pixels requires grim")
    executable = preview_app
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, executable, input_device, tmp_path],
        check=True,
        timeout=45,
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_preview_directory_picker(frontend, tmp_path, request):
    require_linux_reader()
    if not all(shutil.which(tool) for tool in ("bwrap", "fc-match", "labwc", "dbus-daemon")):
        pytest.skip("requires a private Wayland session and an empty client filesystem")
    if subprocess.run([sys.executable, "-c", "from gi.repository import Gio, GLib"], capture_output=True).returncode:
        pytest.skip("the independent desktop portal peer requires Gio")
    source = ROOT / "src/tests/native/gui/linux/PortalGUI.btrc"
    executable = build_app(frontend, source, tmp_path, request)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "--portal", executable, tmp_path],
        check=True,
        timeout=45,
    )


def test_preview_accessibility(preview_app, tmp_path):
    if not ctypes.util.find_library("atspi") or not os.environ.get("BTRC_ATSPI_LIBEXEC"):
        pytest.skip("requires the desktop's AT-SPI client library and bus launcher")
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, "-m", "src.tests.native.gui.wayland_atspi", preview_app, tmp_path],
        cwd=ROOT,
        check=True,
        timeout=45,
    )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_accessible_editor(frontend, tmp_path, request):
    if not ctypes.util.find_library("atspi") or not os.environ.get("BTRC_ATSPI_LIBEXEC"):
        pytest.skip("requires the desktop's AT-SPI client library and bus launcher")
    executable = build_app(frontend, ROOT / "src/tests/native/gui/linux/WaylandAccessibleField.btrc", tmp_path, request)
    subprocess.run(
        [
            SESSION,
            "--wayland",
            "--",
            sys.executable,
            "-m",
            "src.tests.native.gui.wayland_atspi",
            executable,
            tmp_path,
            "--field",
        ],
        cwd=ROOT,
        check=True,
        timeout=45,
    )


def controls_visible(pixels, width, left, top, background):
    def pixel(x, y):
        at = ((top + y) * width + left + x) * 3
        return pixels[at : at + 3]

    return pixel(26, 70) != background and any(pixel(x, y) != background for x in range(16, 140) for y in range(12, 42))


def empty_root_command(executable, work, options=()):
    executable, work = Path(executable).resolve(), Path(work)
    listing = subprocess.check_output(["ldd", executable], text=True)
    assert not any(lib in listing for lib in RUNTIME_FORBIDDEN), listing
    dependencies = re.findall(r"(?:=>\s+|^\s*)(/[^ ]+)\s+\(", listing, re.M)
    assert dependencies and "not found" not in listing
    font = subprocess.check_output(["fc-match", "-f", "%{file}", "Noto Sans"], text=True)
    assert Path(font).is_file()
    config = work / "preview-fonts.conf"
    config.write_text(
        "<fontconfig><dir>/fonts</dir><alias><family>sans-serif</family>"
        "<prefer><family>Noto Sans</family></prefer></alias></fontconfig>"
    )
    socket = Path(os.environ["XDG_RUNTIME_DIR"]) / os.environ["WAYLAND_DISPLAY"]
    command = [
        "bwrap",
        "--die-with-parent",
        "--clearenv",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--dir",
        "/tmp",
        "--dir",
        "/run",
        "--perms",
        "0700",
        "--dir",
        "/run/gui",
        "--ro-bind",
        socket,
        "/run/gui/display",
        "--setenv",
        "WAYLAND_DISPLAY",
        "display",
        "--setenv",
        "XDG_RUNTIME_DIR",
        "/run/gui",
        "--dir",
        "/fonts",
        "--ro-bind",
        font,
        "/fonts/sans.ttf",
        "--ro-bind",
        config,
        "/fonts.conf",
        "--setenv",
        "FONTCONFIG_FILE",
        "/fonts.conf",
        "--setenv",
        "LD_LIBRARY_PATH",
        "/lib",
        "--ro-bind",
        executable,
        "/app",
    ]
    for dependency in dependencies:
        name = Path(dependency).name
        target = dependency if name.startswith("ld-linux") else f"/lib/{name}"
        command.extend(("--ro-bind", dependency, target))
    return [*command, *options, "--", "/app"]


def run_in_root(executable, probe, work):
    command = empty_root_command(executable, work)
    green = bytes((37, 179, 125))
    with connected_mouse(probe) as send, subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as app:
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                assert app.poll() is None, f"app exited during startup: {app.returncode}"
                shot = subprocess.check_output(["grim", "-t", "ppm", "-"])
                header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", shot)
                assert header
                width = int(header[1])
                pixels = shot[header.end() :]
                origin = pixels.find(green * 240)
                if origin >= 0:
                    top, left = divmod(origin // 3, width)

                    if controls_visible(pixels, width, left, top, green):
                        break
            else:
                raise AssertionError("the mounted panel, label and button did not appear")
            x, y = left + 45, top + 75
            send("m", x, y)
            send("d", x, y)
            send("u", x, y)
            output, _ = app.communicate(timeout=8)
            assert app.returncode == 0 and output.strip() == "Clicked Quit", (app.returncode, output)
        finally:
            if app.poll() is None:
                app.kill()


def run_portal(executable, work):
    address = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    options = ["--dir", os.getcwd(), "--chdir", os.getcwd(), "--setenv", "DBUS_SESSION_BUS_ADDRESS", address]
    if address.startswith("unix:path="):
        socket = address.removeprefix("unix:path=").split(",", 1)[0]
        options.extend(("--ro-bind", socket, socket))
    peer = ROOT / "src/tests/native/gui/linux/PortalChooserPeer.py"
    subprocess.run([sys.executable, peer, "--drive-gui", *empty_root_command(executable, work, options)], check=True)
    unavailable = subprocess.run(
        empty_root_command(executable, work, ["--setenv", "DBUS_SESSION_BUS_ADDRESS", "unix:path=/no-session"]),
        check=True,
        capture_output=True,
        text=True,
        timeout=12,
    )
    assert unavailable.stdout.strip() == "3", unavailable


if __name__ == "__main__":
    if sys.argv[1] == "--portal":
        run_portal(*sys.argv[2:])
    else:
        run_in_root(*sys.argv[1:])
