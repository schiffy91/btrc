"""macOS ImageIO/CoreGraphics encoded-image provider conformance."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src" / "stdlib" / "macos_encoded_image_decoder"
FIXTURES = ROOT / "src" / "tests" / "native" / "macos_encoded_image_decoder"
CONFORMANCE = FIXTURES / "MacOsEncodedImageDecoderConformance.btrc"
SMOKE = FIXTURES / "macos_encoded_image_decoder_smoke.c"
FAKE = FIXTURES / "FakeMacOsEncodedImageDecoder.c"
NATIVE = RUNTIME / "btrc_macos_encoded_image_decoder.c"
PACKAGE_NAME = "btrc_stdlib_macos_encoded_image_decoder_runtime"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
APPLE_CLANG = "/usr/bin/clang" if Path("/usr/bin/clang").is_file() else None
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 30

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="ImageIO is available only on macOS")


def _transpile(frontend: str, generated: Path, plan: Path, request: pytest.FixtureRequest) -> None:
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(generated.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--strict-imports",
            "--no-cache",
            "--target",
            "macos-arm64",
            "--emit-link-plan",
            str(plan),
            str(CONFORMANCE),
            "-o",
            str(generated),
        ]
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        command = [
            str(btrcc),
            "--strict-imports",
            "--target",
            "macos-arm64",
            "--emit-link-plan",
            str(plan),
            str(CONFORMANCE),
        ]
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
    )
    if frontend != "python" and completed.returncode == 0:
        generated.write_text(completed.stdout)
    assert completed.returncode == 0 and generated.is_file() and plan.is_file(), completed.stderr


def _strict_build(
    compiler: str, source: Path, implementation: Path, output: Path, *, frameworks: bool = False
) -> subprocess.CompletedProcess[str]:
    command = [
        compiler,
        "-std=c11",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O2",
        f"-I{RUNTIME}",
        str(source),
        str(implementation),
    ]
    if frameworks:
        command.extend(
            [
                "-framework",
                "CoreFoundation",
                "-framework",
                "CoreGraphics",
                "-framework",
                "ImageIO",
            ]
        )
    command.extend(["-lm", "-o", str(output)])
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)


@pytest.mark.skipif(APPLE_CLANG is None, reason="requires Apple Clang")
def test_macos_decoder_native_smoke_and_sanitizers(tmp_path: Path) -> None:
    executable = tmp_path / "macos-encoded-image-smoke"
    built = _strict_build(APPLE_CLANG, SMOKE, NATIVE, executable, frameworks=True)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS MacOsEncodedImageDecoderSmoke\n"
    executable = tmp_path / "macos-encoded-image-smoke-ubsan"
    command = [
        APPLE_CLANG,
        "-std=c11",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O1",
        "-fsanitize=undefined",
        "-fno-omit-frame-pointer",
        f"-I{RUNTIME}",
        str(SMOKE),
        str(NATIVE),
        "-framework",
        "CoreFoundation",
        "-framework",
        "CoreGraphics",
        "-framework",
        "ImageIO",
        "-o",
        str(executable),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert built.returncode == 0, built.stderr
    environment = {
        **os.environ,
        "UBSAN_OPTIONS": "halt_on_error=1",
    }
    ran = subprocess.run(
        [str(executable)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=RUN_TIMEOUT
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS MacOsEncodedImageDecoderSmoke\n"
    leaks = shutil.which("leaks")
    if leaks is not None:
        executable = tmp_path / "macos-encoded-image-smoke-leaks"
        built = _strict_build(APPLE_CLANG, SMOKE, NATIVE, executable, frameworks=True)
        assert built.returncode == 0, built.stderr
        checked = subprocess.run(
            [leaks, "-atExit", "--", str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=RUN_TIMEOUT
        )
        assert checked.returncode == 0, checked.stderr
        assert "0 leaks for 0 total leaked bytes" in checked.stdout


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_macos_decoder_both_frontends_and_strict_compilers(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    generated = tmp_path / f"macos-encoded-image-{compiler}.c"
    plan = tmp_path / f"macos-encoded-image-{compiler}.link.json"
    _transpile(compiler, generated, plan, request)
    if compiler == "btrc":
        reference_generated = tmp_path / "macos-encoded-image-python.c"
        reference_plan = tmp_path / "macos-encoded-image-python.link.json"
        _transpile("python", reference_generated, reference_plan, request)
        assert plan.read_bytes() == reference_plan.read_bytes()
    payload = json.loads(plan.read_text())
    assert payload["frameworks"] == [
        {"name": "CoreFoundation", "package": PACKAGE_NAME},
        {"name": "CoreGraphics", "package": PACKAGE_NAME},
        {"name": "ImageIO", "package": PACKAGE_NAME},
    ]
    assert payload["units"] == [
        {
            "language": "c",
            "package": PACKAGE_NAME,
            "path": str(RUNTIME / "btrc_macos_encoded_image_decoder.c"),
            "standard": "c11",
        }
    ]
    for native_compiler in STRICT_COMPILERS:
        executable = tmp_path / f"macos-encoded-image-{compiler}-{Path(native_compiler).name}"
        built = _strict_build(native_compiler, generated, FAKE, executable)
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout == "PASS MacOsEncodedImageDecoderConformance\n"
    if APPLE_CLANG is not None:
        executable = tmp_path / f"macos-encoded-image-{compiler}-imageio"
        built = _strict_build(APPLE_CLANG, generated, NATIVE, executable, frameworks=True)
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout == "PASS MacOsEncodedImageDecoderConformance\n"


def test_macos_decoder_keeps_native_ownership_inside_provider() -> None:
    source = (ROOT / "src" / "stdlib" / "MacOsEncodedImageDecoder.btrc").read_text()
    assert "DdsEncodedImageDecoder.recognizes(encoded)" in source
    assert source.count("std_macos_encoded_image_release(pixels);") == 2
    assert "image.tryCopyPackedRgba(pixels, pixelBytes)" in source
    native = (RUNTIME / "btrc_macos_encoded_image_decoder.c").read_text()
    assert "CFDataCreateWithBytesNoCopy" in native
    assert "CGImageSourceGetType" in native
    assert "free(pixels);" in native
