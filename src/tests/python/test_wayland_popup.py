"""Real compositor pixels and click-through for transient Wayland tooltips."""

import re
import subprocess
import sys
import time

import pytest

from src.tests.python.test_first_party_wayland_window import SESSION, client, input_device  # noqa: F401


@pytest.mark.parametrize("scale", [1, 2])
def test_tooltip_popup_click_through_scale_and_gpu(client, input_device, scale):  # noqa: F811
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, client, input_device, str(scale)], check=True, timeout=30
    )


def monitor(program, probe, scale):
    scale = int(scale)
    subprocess.run(["wlr-randr", "--output", "HEADLESS-1", "--scale", str(scale)], check=True)
    parent_color = bytes((37, 179, 125))
    tip_color = bytes((171, 49, 109))
    with (
        subprocess.Popen([program, "popup"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0) as app,
        subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:
            assert app.stdout.readline() == b"ready\n"

            def command(value):
                app.stdin.write(value)
                assert app.stdout.readline() == b"ok\n"

            def check(visible):
                end = time.monotonic() + 3
                while time.monotonic() < end:
                    image = subprocess.check_output(["grim", "-t", "ppm", "-"])
                    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", image)
                    assert header
                    width = int(header[1])
                    data = image[header.end() :]
                    parent = data.find(parent_color * (160 * scale))
                    start = data.find(tip_color * (72 * scale))
                    if parent < 0 or (start >= 0) != visible:
                        continue
                    if not visible:
                        return
                    y, x = divmod(start // 3, width)
                    py, px = divmod(parent // 3, width)
                    assert px < x < px + 160 * scale < x + 72 * scale
                    assert py < y < py + 100 * scale
                    assert data.count(tip_color) == 72 * 26 * scale * scale, (data.count(tip_color), x, y, px, py)
                    return x, y
                raise AssertionError("compositor did not present the requested popup state")

            command(b"p")
            x, y = check(True)
            mouse.stdin.write(f"d {x + 4} {y + 2}\nu {x + 4} {y + 2}\n")
            mouse.stdin.flush()
            assert mouse.stdout.readline().strip() == mouse.stdout.readline().strip() == "sent"
            assert app.stdout.readline() == b"parent click\n"
            mouse.stdin.write(f"m {x - 36} {y - 26}\n")
            mouse.stdin.flush()
            assert mouse.stdout.readline().strip() == "sent"
            command(b"g")  # Existing popup survives adoption of the display connection.
            check(True)
            command(b"h")
            check(False)
            command(b"p")  # New popups also use the adopted connection.
            check(True)
            command(b"h")
            check(False)
            command(b"p")
            check(True)
            command(b"w")
            app.stdin.write(b"q")
            assert app.wait(3) == 0
        finally:
            if app.poll() is None:
                app.kill()
            mouse.terminate()


if __name__ == "__main__":
    monitor(*sys.argv[1:])
