"""Real ImageIO provider behavior, typed SDK binding and failure cleanup."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "src/tests/native/macos_encoded_image_decoder"
APPLE_CLANG = "/usr/bin/clang"
PACKAGE_NAME = "btrc_stdlib_runtime"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 60

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="ImageIO is available only on macOS")


def _apple_environment() -> dict[str, str]:
    # Do not select Nix's compiler-rt through the Apple developer-tool shim.
    return {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}


@pytest.fixture
def sdk_environment():
    reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
    if not reader or not Path(reader).is_file():
        pytest.skip("requires the explicitly built native header reader")
    environment = _apple_environment()
    sdk = subprocess.run(
        ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    return {
        **environment,
        "BTRC_NATIVE_SYSROOT": sdk,
        "BTRC_NATIVE_TARGET": f"{architecture}-apple-macosx14.0.0",
        "BTRC_HOME": str(ROOT / "src"),
    }


def _transpile(frontend, fixture, generated, plan, request, environment, *, with_text=False, with_audio=False):
    target = "macos-arm64" if platform.machine() == "arm64" else "macos-x86_64"
    flags = ["--strict-imports", "--target", target, "--emit-link-plan", str(plan), str(fixture)]
    if frontend == "python":
        command = [sys.executable, "-B", "-m", "src.compiler.python.main", "--no-cache", *flags, "-o", str(generated)]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc")), *flags]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**environment, "BTRC_CACHE_DIR": str(generated.parent / "cache")},
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
    if frontend != "python":
        generated.write_text(completed.stdout)
    payload = json.loads(plan.read_text())
    assert payload["units"] == []  # No handwritten decoder implementation.
    names = (
        ("CoreFoundation", "CoreGraphics", "CoreText", "ImageIO")
        if with_text
        else ("CoreFoundation", "CoreGraphics", "ImageIO")
    )
    if with_audio:
        names = ("AudioToolbox", "CoreAudio", *names)
    assert payload["frameworks"] == [{"name": name, "package": PACKAGE_NAME} for name in names]
    return payload


def test_managed_provider_import_composition(compiler, tmp_path, request, sdk_environment):
    _transpile(
        compiler,
        FIXTURES / "ManagedProviderImports.btrc",
        tmp_path / "ManagedProviderImports.c",
        tmp_path / "ManagedProviderImports.link.json",
        request,
        sdk_environment,
        with_text=True,
        with_audio=True,
    )


def _build(source, executable, frameworks, *, sanitized=False, hooks=False, hook_header=None):
    command = [APPLE_CLANG, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
    if sanitized:
        command.extend(["-fsanitize=address,undefined", "-fno-omit-frame-pointer"])
    if hooks:
        command.extend(["-include", str(FIXTURES / "ImageIoFaults.h")])
    if hook_header is not None:
        command.extend(["-include", str(hook_header), f"-I{hook_header.parent}"])
    command.extend([f"-I{FIXTURES}", str(source)])
    for framework in frameworks:
        command.extend(["-framework", framework["name"]])
    command.extend(["-lm", "-o", str(executable)])
    built = subprocess.run(
        command,
        cwd=ROOT,
        env=_apple_environment(),
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr


def _run(executable, *arguments):
    ran = subprocess.run(
        [str(executable), *(str(argument) for argument in arguments)],
        env={**_apple_environment(), "ASAN_OPTIONS": "halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert ran.returncode == 0, ran.stderr
    return ran


@pytest.mark.parametrize(
    "fixture,hooks",
    [
        ("MacOsEncodedImageDecoderConformance", False),
        ("ImageIoCleanup", True),
    ],
)
def test_imageio_provider(compiler, fixture, hooks, tmp_path, request, sdk_environment):
    generated = tmp_path / f"{fixture}-{compiler}.c"
    plan = tmp_path / f"{fixture}-{compiler}.json"
    payload = _transpile(compiler, FIXTURES / f"{fixture}.btrc", generated, plan, request, sdk_environment)
    if compiler == "btrc":
        reference_plan = tmp_path / "reference.json"
        _transpile(
            "python", FIXTURES / f"{fixture}.btrc", tmp_path / "reference.c", reference_plan, request, sdk_environment
        )
        assert plan.read_bytes() == reference_plan.read_bytes()
    arguments = []
    if not hooks:
        fixture_encoder = tmp_path / "tiff-encoder"
        _build(FIXTURES / "ImageIoTiffFixture.c", fixture_encoder, payload["frameworks"])
        tiff = tmp_path / "two-frames.tiff"
        _run(fixture_encoder, tiff)
        assert tiff.is_file()
        arguments.append(tiff)
    for sanitized in (False, True):
        executable = tmp_path / f"{fixture}-{compiler}-{sanitized}"
        _build(generated, executable, payload["frameworks"], sanitized=sanitized, hooks=hooks)
        assert _run(executable, *arguments).stdout == f"PASS {fixture}\n"


def test_system_text_failure_cleanup(compiler, tmp_path, request, sdk_environment):
    source = tmp_path / "SystemTextCleanup.btrc"
    source.write_text("""import Library.MacOSEncodedImageDecoder;
import Library.GUI.MacOS.MacOSSystemText;
import Library.GUI.TextRun;
import Library.Image;
#include <assert.h>
#include "SystemTextFaults.h"
void systemTextBegin(int failure);
int systemTextOutstanding();
int systemTextCreations();
void rasterOnce(int failure) {
    bool caught = false;
    try {
        var text = MacOSSystemText.raster(TextRun("Mgyp café", 20, 28, 700));
        assert(failure == 0 && text.width > 20 && text.height >= 28);
        int coverage = 0;
        for (int y = 0; y < text.height; y++) {
            for (int x = 0; x < text.width; x++) { coverage += text.pixel(x, y).alpha; }
        }
        assert(coverage > 0 && systemTextOutstanding() == 0);
    } catch (string error) { caught = true; }
    assert(caught == (failure != 0));
}
int main(int argc, char** argv) {
    if (argc > 1) { int failure = atoi(argv[1]); systemTextBegin(failure); rasterOnce(failure); return 1; }
    int expected[14] = {10, 0, 1, 3, 3, 4, 5, 6, 7, 8, 9, 9, 9, 9};
    for (int iteration = 0; iteration < 16; iteration++) {
        for (int failure = 0; failure <= 13; failure++) {
            /* These SDK nonnull factories are checked in isolated abort cases. */
            if (failure == 5 || failure == 6 || failure == 9) { continue; }
            systemTextBegin(failure); rasterOnce(failure);
            assert(systemTextOutstanding() == 0 && systemTextCreations() == expected[failure]);
        }
    }
    systemTextBegin(0);
    print("PASS SystemTextCleanup");
    return 0;
}
""")
    generated = tmp_path / "SystemTextCleanup.c"
    payload = _transpile(
        compiler, source, generated, tmp_path / "SystemTextCleanup.json", request, sdk_environment, with_text=True
    )
    for sanitized in (False, True):
        executable = tmp_path / f"SystemTextCleanup-{sanitized}"
        _build(
            generated,
            executable,
            payload["frameworks"],
            sanitized=sanitized,
            hook_header=ROOT / "src/tests/native/gui_surface/SystemTextFaults.h",
        )
        assert _run(executable).stdout == "PASS SystemTextCleanup\n"
        for failure, function in (
            (5, "CTFontDescriptorCreateWithAttributes"),
            (6, "CTFontCreateCopyWithAttributes"),
            (9, "CTLineCreateWithAttributedString"),
        ):
            rejected = subprocess.run(
                [str(executable), str(failure)],
                env=_apple_environment(),
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
            )
            assert rejected.returncode != 0
            assert f"Native call {function}: null result" in rejected.stderr
            assert "AddressSanitizer" not in rejected.stderr and "runtime error:" not in rejected.stderr


def test_imageio_binding_requires_reader_before_emitting_code(tmp_path, monkeypatch):
    from src.compiler.python import Compiler, CompilerOptions

    monkeypatch.delenv("BTRC_NATIVE_HEADER_READER", raising=False)
    source = FIXTURES / "MacOsEncodedImageDecoderConformance.btrc"
    result = Compiler().compile(source.read_text(), str(source), CompilerOptions(use_cache=False, target="macos-arm64"))
    assert not result.successful and not result.c_source
    assert "BTRC_NATIVE_HEADER_READER" in str(result.failure)


@pytest.mark.parametrize("text_first", [False, True])
def test_imageio_and_system_text_share_managed_sdk_resources(compiler, text_first, tmp_path, request, sdk_environment):
    imports = ["Library.MacOSEncodedImageDecoder", "Library.GUI.MacOS.MacOSSystemText"]
    if text_first:
        imports.reverse()
    source = tmp_path / "CombinedNativeRaster.btrc"
    (tmp_path / "ImageIoSamples.btrc").write_text((FIXTURES / "ImageIoSamples.btrc").read_text())
    source.write_text(
        "".join(f"import {module};\n" for module in imports)
        + """import Library.GUI.TextRun;
import Library.Bytes;
import Library.EncodedImage;
import Library.Image;

import ./ImageIoSamples.btrc;
#include <assert.h>

int main() {
	for (int iteration = 0; iteration < 64; iteration++) {
		var text = MacOSSystemText.raster(TextRun("Mgyp café", 20, 28, iteration % 2 == 0 ? 400 : 700));
		assert(text.width > 20 && text.height >= 28);
		int coverage = 0;
		for (int y = 0; y < text.height; y++) {
			for (int x = 0; x < text.width; x++) { coverage += text.pixel(x, y).alpha; }
		}
		assert(coverage > 0);
		var decoded = MacOSEncodedImageDecoder().decode(pngFixture(), EncodedImageDecodeLimits(1024, 4, 4, 16LL));
		assert(decoded.succeeded());
		assert(decoded.image().pixel(1, 0).equals(RGBA(0, 255, 0, 128)));
	}
	print("PASS combined native raster");
	return 0;
}
"""
    )
    generated = tmp_path / "CombinedNativeRaster.c"
    payload = _transpile(
        compiler, source, generated, tmp_path / "CombinedNativeRaster.json", request, sdk_environment, with_text=True
    )
    for sanitized in (False, True):
        executable = tmp_path / f"CombinedNativeRaster-{sanitized}"
        _build(generated, executable, payload["frameworks"], sanitized=sanitized)
        assert _run(executable).stdout == "PASS combined native raster\n"
