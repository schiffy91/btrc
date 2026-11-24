"""Compare a shaped native button label with both its independent glyph mask and compositor readback."""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from src.tests.python.linux_provider_fixtures import require_linux_reader, transpile_provider_program
from src.tests.python.test_first_party_wayland_window import (
    NATIVE,
    PROVIDER,
    SESSION,
    client,  # noqa: F401
    connected_mouse,
    input_device,  # noqa: F401
    native_wayland_root,  # noqa: F401
)
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_wayland_button_title_measurement_and_pixels(frontend, native_wayland_root, input_device, tmp_path, request):  # noqa: F811
    require_linux_reader()
    generated, plan, program = (tmp_path / name for name in ("titles.c", "titles.json", "titles"))
    transpile_provider_program(
        NATIVE / "WaylandButtonTitles.btrc", generated, plan, frontend, request, native_wayland_root
    )
    native = json.loads(plan.read_text())
    assert {item["name"] for item in native["pkg-config"]} <= {"wgpu-native"}
    companion = tmp_path / "WaylandButtonTitles.o"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{PROVIDER}",
            "-c",
            NATIVE / "WaylandButtonTitles.c",
            "-o",
            companion,
        ],
        check=True,
    )
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=program,
        optimization=0,
        compile_flags=["-ffunction-sections", "-fdata-sections"],
        link_flags=[str(companion), "-Wl,--gc-sections", "-lm"],
    )
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    shutil.copyfile(NATIVE.parent / "fixtures/shaping-fixture.ttf", fonts / "title.ttf")
    config = tmp_path / "fonts.conf"
    config.write_text(
        f"<fontconfig><dir>{escape(str(fonts))}</dir>"
        "<alias><family>sans-serif</family><prefer><family>Test</family></prefer></alias></fontconfig>"
    )
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, program, input_device, config], check=True, timeout=40
    )


def compare(program, probe, config, click=None):
    width, height = 160, 60
    with (
        connected_mouse(probe) if click is not None else nullcontext() as send,
        subprocess.Popen([program], stdout=subprocess.PIPE, env={**os.environ, "FONTCONFIG_FILE": config}) as app,
    ):
        try:
            rgba = app.stdout.read(width * height * 4)
            assert len(rgba) == width * height * 4
            rgb = bytes(channel for i, channel in enumerate(rgba) if i % 4 != 3)
            mapped = Path(f"/proc/{app.pid}/maps").read_text()
            assert not any(
                lib in mapped
                for lib in ("libgtk", "libpango", "libcairo", "libfreetype", "libfontconfig", "libwayland-client")
            )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                screen = subprocess.check_output(["grim", "-t", "ppm", "-"])
                header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", screen)
                assert header
                stride = int(header[1]) * 3
                start = screen.find(rgb[: width * 3], header.end())
                if start >= 0 and all(
                    screen[start + y * stride : start + y * stride + width * 3]
                    == rgb[y * width * 3 : (y + 1) * width * 3]
                    for y in range(height)
                ):
                    break
            else:
                raise AssertionError("Compositor did not show the independently measured and rasterized control text")
            if click is not None:
                y, x = divmod((start - header.end()) // 3, int(header[1]))
                px, py = x + click[0], y + click[1]
                send("m", px, py)
                send("d", px, py)
                send("u", px, py)
                assert app.stdout.readline().strip() == b"activated"
            subprocess.run([probe, "close"], check=True)
            assert app.wait(timeout=5) == 0
        finally:
            if app.poll() is None:
                app.kill()


if __name__ == "__main__":
    compare(*sys.argv[1:])
