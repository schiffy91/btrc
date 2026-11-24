"""Drive a genuinely grabbed and repaintable native Wayland menu with a separate input client."""

import re
import select
import subprocess
import sys
import time

from src.tests.python.test_first_party_wayland_window import (
    CLIENT_SOURCES,
    NATIVE,
    PROVIDER,
    SESSION,
    client,  # noqa: F401
    input_device,  # noqa: F401
    wayland_session_env,
)


def test_wayland_menu_popup_pointer_keys_and_outside_dismissal(tmp_path, input_device):  # noqa: F811
    program = tmp_path / "menu"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-pthread",
            f"-I{PROVIDER}",
            NATIVE / "WaylandMenuPopup.c",
            *CLIENT_SOURCES,
            "-o",
            program,
        ],
        check=True,
    )
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, program, input_device],
        env=wayland_session_env(),
        check=True,
        timeout=30,
    )


def color_origin(rgb):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        image = subprocess.check_output(["grim", "-t", "ppm", "-"])
        header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", image)
        assert header
        data, stride = image[header.end() :], int(header[1]) * 3
        pattern = bytes(rgb) * 10
        if pattern not in data:
            continue
        points = []
        for y in range(len(data) // stride):
            at = data.find(pattern, y * stride, (y + 1) * stride)
            if at >= 0:
                points.append(((at - y * stride) // 3, y))
        if points:
            return min(x for x, y in points), min(y for x, y in points)
    raise AssertionError(f"Compositor never displayed {rgb}")


def observe(program, probe):
    with (
        subprocess.Popen([program], stdout=subprocess.PIPE) as app,
        subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:

            def message():
                assert select.select([app.stdout], [], [], 5)[0], "menu application timed out"
                return app.stdout.readline().decode().strip()

            def send(command, x, y):
                mouse.stdin.write(f"{command} {x} {y}\n")
                mouse.stdin.flush()
                assert mouse.stdout.readline().strip() == "sent"

            assert message() == "ready"
            px, py = color_origin((37, 179, 125))

            def open_by_pointer():
                send("d", px + 25, py + 20)
                assert message() == "opened"
                send("u", px + 25, py + 20)
                return color_origin((171, 49, 109))

            x, y = open_by_pointer()
            send("m", x + 20, y + 12)
            send("m", x + 21, y + 13)
            color_origin((100, 58, 211))
            send("d", x + 21, y + 13)
            send("u", x + 21, y + 13)
            assert message() == "menu press 21 13"

            keys = subprocess.run([probe, "keyboard"], input="k", capture_output=True, text=True, check=True)
            assert keys.stdout.strip() == "sent" and message() == "opened"
            x, y = color_origin((171, 49, 109))
            send("e", x + 21, y + 13)
            assert message() == "escape"

            open_by_pointer()
            send("d", px + 190, py + 120)
            send("u", px + 190, py + 120)
            assert message() == "outside dismissed"
            subprocess.run([probe, "close"], check=True)
            assert app.wait(5) == 0
        finally:
            if app.poll() is None:
                app.kill()
            mouse.terminate()


if __name__ == "__main__":
    observe(*sys.argv[1:])
