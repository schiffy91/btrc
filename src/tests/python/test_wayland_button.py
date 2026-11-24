"""Compare first-party Wayland button pixels and activation against a separate compositor client."""

import re
import subprocess
import sys
import time
from pathlib import Path

from src.tests.python.test_first_party_wayland_window import (
    SESSION,
    client,  # noqa: F401
    input_device,  # noqa: F401
    shim_program,
)


def test_wayland_symbol_button_pixels_and_input(input_device, tmp_path):  # noqa: F811
    program = shim_program("WaylandButtons", tmp_path)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, program, input_device], timeout=40, check=True
    )


def check_buttons(program, probe):
    green = bytes((37, 179, 125))
    end = time.monotonic() + 8
    with (
        subprocess.Popen([program], stdout=subprocess.PIPE, text=True) as app,
        subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
        subprocess.Popen([probe, "keyboard"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as keyboard,
    ):
        try:
            assert app.stdout.readline().strip() == "shown"

            def screen():
                data = subprocess.check_output(["grim", "-t", "ppm", "-"])
                hdr = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
                assert hdr
                width = int(hdr[1])
                start = data.find(green * 160, hdr.end())
                if start < 0:
                    return None
                top, left = divmod((start - hdr.end()) // 3, width)

                def pixel(x, y):
                    index = start + (y * width + x) * 3
                    return data[index : index + 3]

                return left, top, pixel

            while time.monotonic() < end:
                snapshot = screen()
                if snapshot:
                    left, top, pixel = snapshot
                    if pixel(33, 29) in (bytes([42]) * 3, bytes([245]) * 3):
                        break
            else:
                raise AssertionError("Wayland compositor never presented the button glyph")
            mapped = Path(f"/proc/{app.pid}/maps").read_text()
            assert not any(name in mapped for name in ("libgtk", "libpango", "libcairo", "libwayland-client"))
            ink = pixel(33, 29)
            assert pixel(78, 33) != ink
            assert pixel(82, 24) == pixel(88, 33) == pixel(98, 28) == ink  # circle stroke, line, rounded rectangle
            assert pixel(87, 24) != ink
            assert pixel(122, 31) != green and pixel(127, 31) == green  # clipped selected button
            assert pixel(35, 75) == green and pixel(106, 75) not in (green, ink)  # transparent and disabled

            def send(operation, x, y):
                mouse.stdin.write(f"{operation} {left + x} {top + y}\n")
                mouse.stdin.flush()
                assert mouse.stdout.readline().strip() == "sent"

            send("d", 30, 28)
            send("u", 61, 28)  # dragged outside
            send("d", 104, 74)
            send("u", 104, 74)  # disabled
            send("d", 130, 29)
            send("u", 130, 29)  # clipped area
            send("d", 35, 75)
            send("u", 35, 75)
            assert app.stdout.readline().strip() == "pressed 3"
            send("d", 30, 28)
            send("u", 30, 28)
            assert app.stdout.readline().strip() == "pressed 1"
            keyboard.stdin.write("k")
            keyboard.stdin.flush()
            assert keyboard.stdout.readline().strip() == "sent"
            assert app.stdout.readline().strip() == "pressed 1"
            subprocess.run([probe, "close"], check=True)
            assert app.wait(timeout=5) == 0
        finally:
            mouse.stdin.close()
            keyboard.stdin.close()
            if app.poll() is None:
                app.kill()


if __name__ == "__main__":
    check_buttons(*sys.argv[1:])
