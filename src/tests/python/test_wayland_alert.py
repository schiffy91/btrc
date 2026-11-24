"""Dismiss real public window alerts and verify the owner's input stays blocked."""

import ctypes.util
import os
import pty
import re
import select
import socket
import struct
import subprocess
import sys
import time

import pytest

from src.tests.python.test_first_party_wayland_window import (
    CLIENT_SOURCES,
    NATIVE,
    PROVIDER,
    ROOT,
    SESSION,
    client,  # noqa: F401
    connected_mouse,
    input_device,  # noqa: F401
)
from src.tests.python.test_wayland_public_preview import build_app, empty_root_command


@pytest.mark.skipif(sys.platform != "linux", reason="the native Wayland client requires Linux")
def test_optional_modal_protocol(tmp_path):
    probe = tmp_path / "modal-protocol"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-pthread",
            f"-I{PROVIDER}",
            NATIVE / "WaylandModalProtocol.c",
            *CLIENT_SOURCES,
            "-o",
            probe,
        ],
        check=True,
    )
    for advertised in (0, 43):
        parent, child = socket.socketpair()
        with parent, child:
            subprocess.run(
                [probe, str(advertised)],
                env={**os.environ, "WAYLAND_SOCKET": str(child.fileno())},
                pass_fds=(child.fileno(),),
                check=True,
                timeout=3,
            )
            child.close()
            with parent.makefile("rb") as peer:
                frames = []
                while header := peer.read(8):
                    obj, word = struct.unpack("=II", header)
                    frames.append((obj, word & 0xFFFF, peer.read((word >> 16) - 8)))
        assert frames[0] == (4, 1, struct.pack("=I", 3))  # xdg_toplevel.set_parent
        if not advertised:
            assert len(frames) == 1
            continue
        interface = b"xdg_wm_dialog_v1\0"
        name = interface.ljust((len(interface) + 3) // 4 * 4, b"\0")
        assert frames[1:] == [
            (2, 0, struct.pack("=II", 43, len(interface)) + name + struct.pack("=II", 1, 5)),  # wl_registry.bind
            (5, 1, struct.pack("=II", 6, 4)),  # xdg_wm_dialog_v1.get_xdg_dialog
            (6, 1, b""),  # xdg_dialog_v1.set_modal
        ]


@pytest.fixture(scope="module", params=["python", "selfhost"])
def alert_app(request, tmp_path_factory):
    work = tmp_path_factory.mktemp("wayland-alert-" + request.param)
    return build_app(request.param, ROOT / "src/tests/native/gui/WaylandAlert.btrc", work, request, timeout=1200)


def test_public_alert(alert_app, input_device, tmp_path):  # noqa: F811
    app = alert_app
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, app, input_device, tmp_path], check=True, timeout=90
    )


def test_accessible_modal_alerts(alert_app, tmp_path):
    if not ctypes.util.find_library("atspi") or not os.environ.get("BTRC_ATSPI_LIBEXEC"):
        pytest.skip("requires the desktop's AT-SPI client library and bus launcher")
    subprocess.run(
        [
            SESSION,
            "--wayland",
            "--",
            sys.executable,
            "-m",
            "src.tests.native.gui.wayland_atspi",
            alert_app,
            tmp_path,
            "--alerts",
        ],
        cwd=ROOT,
        check=True,
        timeout=90,
    )


def frame():
    data = subprocess.check_output(["grim", "-t", "ppm", "-"])
    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
    return data[header.end() :], int(header[1]) * 3, int(header[2])


def rectangle(color, data, stride, height, minimum=150):
    pattern = bytes(color) * minimum
    left, top, right, bottom = stride, height, -1, -1
    for y in range(height):
        row = data[y * stride : (y + 1) * stride]
        x = row.find(pattern)
        if x >= 0:
            left, right = min(left, x // 3), max(right, row.rfind(pattern) // 3 + minimum)
            top, bottom = min(top, y), y + 1
    return (left, top, right, bottom) if right > left else None


def ink(data, stride, box, shade):
    left, top, right, bottom = box
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            offset = y * stride + x * 3
            if abs(data[offset] - shade) > 100:
                count += 1
    return count


def alert(timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data, stride, height = frame()
        parent = rectangle((37, 179, 125), data, stride, height, minimum=12)
        if not parent:
            continue
        for shade in (43, 248):
            dialog = rectangle((shade,) * 3, data, stride, height)
            if dialog:
                x, y, right, bottom = dialog
                if (
                    240 <= right - x <= 540
                    and 100 <= bottom - y <= 470
                    and ink(data, stride, (x + 19, y + 16, right - 20, y + 38), shade) > 20
                    and ink(data, stride, (x + 19, y + 40, right - 20, y + 78), shade) > 20
                ):
                    return parent, dialog
    raise AssertionError("the compositor did not show the alert's title and detail")


def observe(program, probe, work):
    master, slave = pty.openpty()
    with (
        os.fdopen(master, "rb", buffering=0) as report,
        os.fdopen(slave, "wb", buffering=0) as console,
        connected_mouse(probe) as send,
        subprocess.Popen(empty_root_command(program, work), stdout=console) as app,
    ):
        try:

            def click(x, y):
                send("d", x, y)
                send("u", x, y)

            def message(expected):
                assert select.select([report], [], [], 8)[0], f"waiting for {expected}, exit {app.poll()}"
                assert report.readline().decode().strip() == expected

            parent, dialog = alert()
            px, py = parent[:2]
            click(px + 50, py + 25)
            assert not select.select([report], [], [], 0.25)[0], "a parent action or dismissal escaped the modal"
            parent, dialog = alert()
            x, y = dialog[:2]
            click(x + 30, y + 25)
            send("e", x + 30, y + 25)
            message("keyboard dismissed")
            parent, dialog = alert()
            right, bottom = dialog[2:]
            click(right - 64, bottom - 32)
            message("pointer dismissed")
            # First layout shapes every line before mapping this large alert.
            _, (x, y, right, bottom) = alert(timeout=32)
            assert bottom - y > 350

            def detail_pixels():
                data, stride, _ = frame()
                return b"".join(
                    data[row * stride + (x + 20) * 3 : row * stride + (right - 40) * 3]
                    for row in range(y + 50, y + 100)
                )

            initial = detail_pixels()
            send("r", x + 12, y + 120)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and detail_pixels() == initial:
                pass
            assert detail_pixels() != initial, "the long indivisible detail did not pan"
            initial = detail_pixels()
            send("v", x + 12, y + 120)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and detail_pixels() == initial:
                pass
            assert detail_pixels() != initial, "long alert content did not scroll"
            subprocess.run([probe, "close-title", "Long alert"], check=True)
            message("close requested")
            click(px + 50, py + 25)
            message("parent click")
            assert app.wait(8) == 0
        finally:
            if app.poll() is None:
                app.kill()


if __name__ == "__main__":
    observe(*sys.argv[1:])
