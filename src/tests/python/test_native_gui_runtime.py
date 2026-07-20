import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUI = ROOT / "src" / "stdlib" / "gui"
HARNESS = ROOT / "src" / "tests" / "native" / "gui_runtime.c"


def test_headless_gui_runtime_is_strict_c11_and_safe(tmp_path: Path) -> None:
    font_source = (GUI / "btrc_gui_font.c").read_text()
    assert "gui_color_apply_coverage(rgba, cov)" in font_source
    assert "| (uint32_t)cov" not in font_source

    executable = tmp_path / "gui-runtime"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-pthread",
            f"-I{GUI}",
            str(HARNESS),
            str(GUI / "btrc_gui.c"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    ppm = tmp_path / "surface.ppm"
    subprocess.run([str(executable), str(ppm)], check=True)
    pixels = b"\xaa\x00\x55" + b"\x00\x00\xff" * 8
    assert ppm.read_bytes() == b"P6\n3 3\n255\n" + pixels
