"""GUI and GPU programs on the iOS and iPadOS simulators, beyond the conformance suite.

The triangle example (examples/triangle) draws through wgpu-native's Metal
backend into a UIKit window and reads its own pixels back. The screen-order
fixture (src/tests/native/gui/ios/ScreenOrder.btrc) holds one control over a
window's drawn content while the driver looks at the simulator's screen: a
capture composes the controls over the frame itself, so only the screen says
whether the system shows them there.

Both are built through each compiler and run on one iPhone and one iPad
simulator (src/tests/python/ios_simulator_fixtures.py). They run where
BTRC_IOS_UI_DEVICES asks for them, and are never physical-device evidence.
"""

import struct
from pathlib import Path

import pytest

from src.tests.python.ios_simulator_fixtures import FRONTENDS, simulators  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
TRIANGLE = REPO / "examples/triangle/Triangle.btrc"
SCREEN_ORDER = REPO / "src/tests/native/gui/ios/ScreenOrder.btrc"
# The fixture's panel, in the window's points.
PANEL = (120, 80)
# One worker owns the simulator: a device is booted, installed on and sent input by one process.
pytestmark = pytest.mark.xdist_group(name="ios_ui")


class Bitmap:
    """An uncompressed 24- or 32-bit BMP, as `simctl io screenshot --type=bmp` writes one."""

    def __init__(self, path):
        data = Path(path).read_bytes()
        assert data[:2] == b"BM", "the screenshot is not a bitmap"
        offset, _, width, height, _, depth, compression = struct.unpack_from("<IIiiHHI", data, 10)
        assert depth in (24, 32) and compression in (0, 3), (
            f"an unexpected bitmap: {depth} bits, compression {compression}"
        )
        self.width, self.height, self.step = width, abs(height), depth // 8
        self.stride = (width * self.step + 3) & ~3
        self.rows = data[offset : offset + self.stride * self.height]
        self.bottom_up = height > 0

    def box(self, wanted):
        """(left, top, right, bottom, count) of the pixels `wanted(red, green, blue)` accepts, or None."""
        left, top, right, bottom, count = self.width, self.height, -1, -1, 0
        for line in range(self.height):
            y = self.height - 1 - line if self.bottom_up else line
            row = self.rows[line * self.stride : line * self.stride + self.width * self.step]
            for x in range(self.width):
                blue, green, red = row[x * self.step : x * self.step + 3]
                if wanted(red, green, blue):
                    count += 1
                    left, right, top, bottom = min(left, x), max(right, x), min(top, y), max(bottom, y)
        return None if count == 0 else (left, top, right, bottom, count)


def red(r, g, b):
    """The fixture's red, in whatever colour space the screen is read back in."""
    return r > 150 and g < 100 and b < 100 and r - max(g, b) > 80


@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("device_class", ["iphone", "ipad"])
def test_the_triangle_example_verifies_its_pixels_on_the_simulator(simulators, request, device_class, frontend):  # noqa: F811
    runner = simulators.runner(device_class, "triangle", TRIANGLE, frontend, False, request)
    status, stdout, stderr = runner.run(["--verify"], {}, 120)
    report = f"triangle --verify on {simulators.host.provenance()['device']} ({frontend})\n{stdout}{stderr}"
    assert status == 0, report
    assert stdout.splitlines()[-1:] == ["PASS: native triangle pixels and shutdown"], report


@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("device_class", ["iphone", "ipad"])
def test_a_control_shows_over_drawn_content_on_the_screen(simulators, request, tmp_path, device_class, frontend):  # noqa: F811
    runner = simulators.runner(device_class, "screenorder", SCREEN_ORDER, frontend, False, request)
    picture = tmp_path / "screen.bmp"
    status, stdout, stderr = runner.run(["8"], {}, 60, observe=(4.0, lambda: simulators.screenshot(picture)))
    report = f"screen order on {simulators.host.provenance()['device']} ({frontend})\n{stdout}{stderr}"
    assert status == 0, report
    assert picture.is_file(), f"the program ended before the screen was read\n{report}"
    found = Bitmap(picture).box(red)
    assert found is not None, f"the panel is not on the screen: something lies over it\n{report}"
    left, top, right, bottom, count = found
    width, height = right - left + 1, bottom - top + 1
    scale = width / PANEL[0]
    # The panel, whole and nothing else red: its points at the screen's two or three pixels to a point.
    assert abs(scale - round(scale)) < 0.02 and round(scale) in (2, 3), (
        f"the panel is {width} by {height} pixels\n{report}"
    )
    assert abs(height - PANEL[1] * scale) <= 2, f"the panel is {width} by {height} pixels\n{report}"
    assert count >= 0.98 * width * height, f"only {count} of the panel's {width * height} pixels show\n{report}"


@pytest.mark.parametrize("frontend", FRONTENDS)
def test_shared_frame_reconnects_and_presents_the_surface(simulators, request, tmp_path, frontend):  # noqa: F811
    source = REPO / "src/tests/native/gui/ios/shared_frame/Main.btrc"
    runner = simulators.runner("iphone", "sharedframe", source, frontend, False, request)
    capture = tmp_path / "shared-frame.bmp"
    status, stdout, stderr = runner.run([], {}, 60, observe=(4.0, lambda: simulators.screenshot(capture)))
    assert status == 0, stdout + stderr
    bitmap = Bitmap(capture)
    top = bitmap.box(red)
    bottom = bitmap.box(lambda r, g, b: b > 150 and r < 100 and g < 100)
    assert top and bottom, "the simulator screen is missing the shared frame's two bands"
    assert top[4] > 5000 and bottom[4] > 5000
    assert abs(top[0] - bottom[0]) < 3 and abs(top[2] - bottom[2]) < 3
    assert abs(top[3] + 1 - bottom[1]) < 3
