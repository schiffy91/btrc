import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget

ROOT = Path(__file__).resolve().parents[3]
GUI = ROOT / "src" / "stdlib" / "GUI"
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
    subprocess.run([str(executable)], check=True, timeout=30)


def _transpile_gui(source, tmp_path, request, frontend):
    generated = tmp_path / "Surface.c"
    environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
    target = PackageTarget.parse(None)
    target_flags = ["--target", f"{target.operating_system}-{target.architecture}"]
    command = (
        [
            sys.executable,
            "-B",
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--no-stdlib",
            *target_flags,
            str(source),
            "-o",
            str(generated),
        ]
        if frontend == "python"
        else [str(request.getfixturevalue("immutable_btrcc")), "--no-stdlib", *target_flags, str(source)]
    )
    compiled = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout)
    assert "btrc_gui_surface_create" not in generated.read_text()
    if sys.platform == "darwin":
        environment.pop("DEVELOPER_DIR", None)
        environment.pop("SDKROOT", None)
    return generated, environment


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_btrc_owns_gui_surface(tmp_path: Path, request, frontend, sanitized) -> None:
    source = ROOT / "src/tests/native/gui_surface/GuiSurfaceConformance.btrc"
    generated, environment = _transpile_gui(source, tmp_path, request, frontend)
    executable = tmp_path / "surface"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    compiler = "/usr/bin/clang" if sys.platform == "darwin" else "cc"
    faults = source.parent
    generated_object = tmp_path / "Surface.o"
    result = subprocess.run(
        [
            compiler,
            "-O2",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-pthread",
            *flags,
            f"-I{GUI}",
            f"-I{ROOT / 'src/runtime/c'}",
            "-include",
            str(faults / "AllocationFaults.h"),
            "-c",
            str(generated),
            "-o",
            str(generated_object),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [
            compiler,
            "-O2",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-pthread",
            *flags,
            f"-I{GUI}",
            str(generated_object),
            str(GUI / "btrc_gui.c"),
            str(faults / "AllocationFaults.c"),
            "-o",
            str(executable),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    ppm = tmp_path / "surface.ppm"
    result = subprocess.run([str(executable), str(ppm)], env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: BTRC-owned GUI pixels\n"
    pixels = b"\xaa\x00\x55" + b"\x00\x00\xff" * 8
    assert ppm.read_bytes() == b"P6\n3 3\n255\n" + pixels


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("consumer", ["Main", "Declarative", "GuiFontConformance", "GuiWindowConformance"])
def test_gui_consumers_use_btrc_pixels(tmp_path, request, frontend, consumer):
    uses_font = consumer == "GuiFontConformance"
    uses_window = consumer == "GuiWindowConformance"
    if uses_window and os.environ.get("BTRC_REAL_WINDOW_TEST") != "1":
        pytest.skip("enable BTRC_REAL_WINDOW_TEST=1 for the real standalone GLFW/OpenGL window")
    font = next(
        (
            path
            for path in [
                Path(os.environ.get("BTRC_TEST_FONT", "/nonexistent")),
                Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            ]
            if path.is_file()
        ),
        None,
    )
    if uses_font and (font is None or not os.environ.get("FONT_CFLAGS")):
        pytest.skip("requires FreeType headers/link flags and a real font")
    original = (
        ROOT / "src/tests/native/gui_surface" if uses_font or uses_window else ROOT / "examples/gui"
    ) / f"{consumer}.btrc"
    source = tmp_path / f"{consumer}.btrc"
    # Keep the existing examples' output inside this isolated test directory.
    source.write_text(
        original.read_text()
        .replace("/tmp/gui_demo.ppm", str(tmp_path / "demo.ppm"))
        .replace("/tmp/gui_declarative.ppm", str(tmp_path / "declarative.ppm"))
    )
    generated, environment = _transpile_gui(source, tmp_path, request, frontend)
    compiler = "/usr/bin/clang" if sys.platform == "darwin" else "cc"
    executable = tmp_path / "consumer"
    native = [str(GUI / "btrc_gui.c")]
    flags = []
    if uses_font:
        native.append(str(GUI / "btrc_gui_font.c"))
        flags = [*shlex.split(os.environ["FONT_CFLAGS"]), *shlex.split(os.environ["FONT_LDFLAGS"])]
    if uses_window:
        native.append(str(GUI / "btrc_gui_window.c"))
        glfw = subprocess.run(["pkg-config", "--libs", "glfw3"], capture_output=True, text=True, check=True, timeout=30)
        flags = [
            *shlex.split(os.environ.get("GPU_CFLAGS", "")),
            *shlex.split(glfw.stdout),
            "-DGL_SILENCE_DEPRECATION",
            *(["-framework", "OpenGL"] if sys.platform == "darwin" else ["-lGL"]),
        ]
    compiled = subprocess.run(
        [
            compiler,
            "-O2",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-pthread",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            f"-I{GUI}",
            f"-I{ROOT / 'src/runtime/c'}",
            str(generated),
            *native,
            *flags,
            "-lm",
            "-o",
            str(executable),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run(
        [str(executable), *([str(font)] if uses_font else [])],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    expected = "GUI TESTS PASSED"
    if uses_font:
        expected = "PASS: FreeType draws into BTRC-owned pixels"
    if uses_window:
        expected = "PASS: native window presents BTRC-owned pixels"
    assert expected in completed.stdout
