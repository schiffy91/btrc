"""Drive keyed ISelect with a separate input client against a real compositor."""

import os
import pty
import re
import select
import subprocess
import sys
import time

import pytest

from src.tests.python.test_first_party_wayland_window import (
    ROOT,
    SESSION,
    client,  # noqa: F401
    input_device,  # noqa: F401
)
from src.tests.python.test_wayland_public_preview import build_app, empty_root_command


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_public_wayland_select(frontend, input_device, tmp_path, request):  # noqa: F811
    program = build_app(frontend, ROOT / "src/tests/native/gui/WaylandSelect.btrc", tmp_path, request)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, program, input_device, tmp_path], check=True, timeout=75
    )


def screenshot():
    image = subprocess.check_output(["grim", "-t", "ppm", "-"])
    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", image)
    return image[header.end() :], int(header[1]) * 3, int(header[2])


def bounds(rgb, expected=None):
    deadline = time.monotonic() + 5
    pattern = bytes(rgb) * 12
    while time.monotonic() < deadline:
        data, stride, height = screenshot()
        if pattern not in data:
            continue
        xs, ys = [], []
        for y in range(height):
            row = data[y * stride : (y + 1) * stride]
            x = row.find(pattern)
            if x >= 0:
                xs.append(x // 3)
                ys.append(y)
        if xs:
            result = min(xs), min(ys), max(ys) - min(ys) + 1
            if expected is None or result == expected:
                return result
    raise AssertionError(f"No matching compositor frame for {rgb}, expected bounds {expected}")


def observe(program, device, work):
    blue = (53, 110, 190)
    master, slave = pty.openpty()
    with (
        os.fdopen(master, "rb", buffering=0) as report,
        os.fdopen(slave, "wb", buffering=0) as console,
        subprocess.Popen(empty_root_command(program, work), stdout=console) as app,
        subprocess.Popen([device, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:

            def message(expected):
                assert select.select([report], [], [], 6)[0], f"waiting for {expected}, exit {app.poll()}"
                assert report.readline().decode().strip() == expected

            def send(command, x, y):
                mouse.stdin.write(f"{command} {x} {y}\n")
                mouse.stdin.flush()
                assert mouse.stdout.readline().strip() == "sent"

            def click(x, y):
                send("d", x, y)
                send("u", x, y)

            px, py, _ = bounds((37, 179, 125))
            click(px + 30, py + 25)
            x, y, height = bounds(blue)
            assert height >= 20
            # Roll down one row in the long list. The original highlight
            # moves above the viewport and rolling back restores its pixels.
            send("v", x - 2, y + 6)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if bytes(blue) * 12 not in screenshot()[0]:
                    break
            else:
                raise AssertionError("scrolling did not move the selected row off screen")
            send("w", x - 2, y + 6)
            bounds(blue, (x, y, height))
            click(x + 20, y + height + height // 2)  # Disabled row.
            bounds(blue, (x, y, height))
            send("m", x + 30, y + height * 2 + height // 2)
            message("reordered")
            # The previous third row is now first and retains its stable key.
            bounds(blue, (x, y, height))
            click(x + 25, y + height // 2)
            message("committed")

            keys = subprocess.run([device, "keyboard"], input="k", capture_output=True, text=True, check=True)
            assert keys.stdout.strip() == "sent"
            x, y, height = bounds(blue)
            send("j", x - 2, y + 6)
            bounds(blue, (x, y + height, height))
            send("e", x - 2, y + 6)
            message("cancelled")

            click(px + 30, py + 25)
            bounds(blue)
            click(px + 208, py + 100)  # Outside the menu but in the same client.
            message("cancelled")

            click(px + 30, py + 25)
            x, y, height = bounds(blue)
            send("m", x + 25, y + height + height // 2)
            message("cancelled")
            assert app.wait(timeout=6) == 0
        finally:
            if app.poll() is None:
                app.kill()
            mouse.terminate()


if __name__ == "__main__":
    observe(*sys.argv[1:])
