import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget

ROOT = Path(__file__).resolve().parents[3]
GUI = ROOT / "src" / "stdlib" / "GUI"


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
def test_owned_font_snapshots_and_surface_selection(tmp_path: Path, request, frontend, sanitized) -> None:
    source = ROOT / "src/tests/native/gui_surface/FontSnapshotConformance.btrc"
    generated, environment = _transpile_gui(source, tmp_path, request, frontend)
    executable = tmp_path / "font-snapshots"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    subprocess.run(
        [
            "/usr/bin/clang" if sys.platform == "darwin" else "cc",
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
            str(generated),
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    completed = subprocess.run(
        [str(executable)],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "PASS: owned signed-pitch font snapshots" in completed.stdout


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
@pytest.mark.parametrize("consumer", ["Main", "Declarative"])
def test_gui_consumers_use_btrc_pixels(tmp_path, request, frontend, consumer):
    original = ROOT / "examples/gui" / f"{consumer}.btrc"
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
        [str(executable)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GUI TESTS PASSED" in completed.stdout
