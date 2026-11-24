"""Hover real public native sliders and buttons and examine the compositor's tooltip frames."""

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from xml.sax.saxutils import escape

import pytest

from src.tests.python.linux_provider_fixtures import require_linux_reader, transpile_provider_program
from src.tests.python.test_first_party_wayland_window import (
    NATIVE,
    PROVIDER,
    SESSION,
    client,  # noqa: F401
    input_device,  # noqa: F401
    native_wayland_root,  # noqa: F401
    wayland_session_env,
)
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_public_tooltips(frontend, native_wayland_root, input_device, tmp_path, request):  # noqa: F811
    require_linux_reader()
    if subprocess.run(["pkg-config", "--exists", "wgpu-native"]).returncode:
        pytest.skip("the shared GUI painter imports the WebGPU SDK")
    generated, plan, program = [tmp_path / name for name in ("tooltip.c", "plan.json", "tooltip")]
    transpile_provider_program(NATIVE / "WaylandTooltips.btrc", generated, plan, frontend, request, native_wayland_root)
    helper = tmp_path / "probe.o"
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
            NATIVE / "WaylandTooltips.c",
            "-o",
            helper,
        ],
        check=True,
    )
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=program,
        optimization=0,
        compile_flags=["-ffunction-sections", "-fdata-sections"],
        link_flags=[str(helper), "-Wl,--gc-sections", "-lm"],
    )
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    shutil.copyfile(NATIVE.parent / "fixtures/shaping-fixture.ttf", fonts / "font.ttf")
    config = tmp_path / "fonts.conf"
    config.write_text(
        f"<fontconfig><dir>{escape(str(fonts))}</dir><alias><family>sans-serif</family><prefer><family>Test</family></prefer></alias></fontconfig>"
    )
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, program, input_device, config],
        env=wayland_session_env(),
        check=True,
        timeout=40,
    )


def monitor(program, probe, config):
    def scan():
        data = subprocess.check_output(["grim", "-t", "ppm", "-"])
        h = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
        assert h
        return int(h[1]), data[h.end() :]

    with (
        subprocess.Popen(
            [program],
            env={**os.environ, "FONTCONFIG_FILE": config},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        ) as app,
        subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:
            end = time.monotonic() + 6
            while time.monotonic() < end:
                width, pixels = scan()
                start = pixels.find(bytes((37, 179, 125)) * 180)
                if start >= 0:
                    break
            else:
                raise AssertionError("native controls did not appear")
            top, left = divmod(start // 3, width)

            def move(x, y, operation="m"):
                mouse.stdin.write(f"{operation} {left + x} {top + y}\n")
                mouse.stdin.flush()
                assert mouse.stdout.readline().strip() == "sent"

            def command(value):
                app.stdin.write(value)
                assert app.stdout.readline() == b"ok\n"

            def tooltip(x, y):
                width, data = scan()
                pos = ((top + y) * width + left + x) * 3
                if data[pos + 45 * 3 : pos + 46 * 3] != bytes((48, 48, 48)):
                    return 0
                # Whole popup is a transient above the window. Count separate
                # glyph bands in its first 48 pixels after the pointer anchor.
                bands = 0
                had_ink = False
                for row in range(6, 64):
                    offset = pos + row * width * 3
                    if data[offset + 50 * 3 : offset + 51 * 3] != bytes((48, 48, 48)):
                        break
                    ink = False
                    for col in range(7, 45):
                        rgb = data[offset + col * 3 : offset + col * 3 + 3]
                        if rgb[0] != rgb[1] or rgb[0] != rgb[2]:
                            continue
                        if rgb[0] >= 200:
                            ink = True
                    if ink and not had_ink:
                        bands += 1
                    had_ink = ink
                return bands

            def expect(x, y, lines):
                until = time.monotonic() + 2.5
                while time.monotonic() < until:
                    if tooltip(x, y) == lines:
                        return
                raise AssertionError(f"expected {lines} tooltip text bands at {x},{y}")

            move(54, 40)
            assert tooltip(56, 55) == 0
            expect(56, 55, 2)
            command(b"d")
            expect(56, 55, 0)
            move(140, 42)
            expect(142, 57, 1)
            command(b"r")
            expect(142, 57, 2)
            command(b"c")
            expect(142, 57, 0)
            command(b"e")
            move(54, 40)
            expect(56, 55, 2)
            move(54, 40, "d")
            move(54, 40, "u")
            expect(56, 55, 0)
            move(10, 85)
            command(b"q")
            assert app.wait(3) == 0
        finally:
            if app.poll() is None:
                app.kill()
            mouse.terminate()


if __name__ == "__main__":
    monitor(*sys.argv[1:])
