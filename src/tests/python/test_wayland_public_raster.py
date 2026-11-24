"""Exercise standalone public text images without a toolkit or system font renderer."""

import os
import shlex
import struct
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import pytest

from src.tests.python.test_first_party_wayland_window import wayland_session_env
from src.tests.python.test_wayland_public_preview import (
    ROOT,
    SESSION,
    build_app,
    empty_root_command,
    matched_sans_font,
)


@pytest.fixture(scope="module", params=["python", "selfhost"])
def rasters(request, tmp_path_factory):
    frontend = request.param
    tmp_path = tmp_path_factory.mktemp(f"wayland-raster-{frontend}")
    executable = build_app(frontend, ROOT / "src/tests/native/gui/linux/WaylandRaster.btrc", tmp_path, request)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, executable, tmp_path],
        env=wayland_session_env(),
        check=True,
    )
    return tmp_path


def test_owned_text_images(rasters):
    images = sorted(rasters.glob("raster-*.bmp"))
    assert len(images) == 28
    samples = []
    for index in range(len(images)):
        bmp = (rasters / f"raster-{index}.bmp").read_bytes()
        assert bmp[:2] == b"BM"
        offset = struct.unpack_from("<I", bmp, 10)[0]
        width, height, planes, bits = struct.unpack_from("<iiHH", bmp, 18)
        assert planes == 1 and bits == 32 and width > 0 and height <= -(41 if index % 2 else 17)
        pixels = bmp[offset : offset + 4 * width * abs(height)]
        assert len(pixels) == 4 * width * abs(height)
        assert all(pixels[i::4] == b"\xff" * (width * abs(height)) for i in range(3))
        alpha = pixels[3::4]
        if index < 4:
            assert not any(alpha)
        else:
            assert any(0 < value < 255 for value in alpha)
        samples.append((width, alpha))
    for first in range(4, len(images), 4):
        assert samples[first] != samples[first + 2]
        assert samples[first + 1][0] > samples[first][0]


@pytest.fixture(scope="module")
def oracle(tmp_path_factory):
    pkg = subprocess.run(["pkg-config", "--cflags", "--libs", "pangocairo"], capture_output=True, text=True)
    if pkg.returncode:
        pytest.skip("the independent Pango/Cairo comparison needs its host SDK")
    folder = tmp_path_factory.mktemp("pango-raster-oracle")
    program = folder / "oracle"
    subprocess.run(
        ["cc", ROOT / "src/tests/native/gui/linux/PangoRasterOracle.c", *shlex.split(pkg.stdout), "-o", program],
        check=True,
    )
    fonts = folder / "fonts"
    fonts.mkdir()
    family = "Noto Sans"
    for style in ("Regular", "Bold"):
        path, matched_family = matched_sans_font(style)
        if style == "Regular":
            family = matched_family
        (fonts / f"{style}.ttf").symlink_to(path)
    config = folder / "fonts.conf"
    config.write_text(
        f"<fontconfig><dir>{fonts}</dir><alias><family>sans-serif</family>"
        f"<prefer><family>{xml_escape(family)}</family></prefer></alias></fontconfig>"
    )
    return program, config


def test_standalone_pixels_match_the_desktop(rasters, oracle):
    program, config = oracle
    env = {**os.environ, "FONTCONFIG_FILE": str(config)}
    index = 0
    for text in (" ", "j", "Ágjpq", "fi AV", "Hello, conformance", "X\tY", "A  "):
        for weight in (400, 700):
            for size, height in ((13, 17), (24, 41)):
                rendered = subprocess.check_output([program, text, str(size), str(height), str(weight)], env=env)
                dimensions, alpha = rendered.split(b"\n", 1)
                bmp = (rasters / f"raster-{index}.bmp").read_bytes()
                w, h = struct.unpack_from("<ii", bmp, 18)
                offset = struct.unpack_from("<I", bmp, 10)[0]
                assert dimensions == f"{w} {-h}".encode()
                assert alpha == bmp[offset + 3 :: 4], (text, weight, size)
                index += 1


def font_path(style):
    return matched_sans_font(style)[0]


def run(executable, work):
    executable, work = Path(executable), Path(work)
    options = ["--ro-bind", font_path("Bold"), "/fonts/bold.ttf", "--bind", str(work), "/out", "--chdir", "/out"]
    command = empty_root_command(executable, work, options)
    result = subprocess.run(command, capture_output=True, check=True, text=True, timeout=120)
    assert result.stdout.strip() == "PASS public text raster", result.stdout


if __name__ == "__main__":
    run(*sys.argv[1:])
