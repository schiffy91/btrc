"""End-to-end tests for FloatImage, RawMosaic, 12/14/16-bit lossless JPEG CFA, and ImageCodec."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def _run_btrc(
    native_project, native_compile, source_code: str, *, sanitize: bool = False
) -> subprocess.CompletedProcess:
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "imageCodecE2E"\n')
    source.write_text(source_code)
    plan = root / "Probe.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Probe.c"
    generated.write_text(compiled.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    binary = root / ("probe_san" if sanitize else "probe")
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=binary, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    return subprocess.run([str(binary)], capture_output=True, text=True, check=False, timeout=60)


@pytest.mark.parametrize("sanitize", [False, True])
def test_float_image_and_lossless_cfa(native_project, native_compile, sanitize):
    program = """import Library.Array;
import Library.Bytes;
import Library.Image.FloatImage;
import Library.Image.JPEG;
import Library.Image.Pixels;
import Library.Image.RawMosaic;
import Library.IO;
import Library.Math;
import Library.Testing;

int main() {
\t/* 1. FloatImage sRGB/linear conversion and FloatImageDiff oracle. */
\tFloatImage a = FloatImage(16, 12);
\tFloatImage b = FloatImage(16, 12);
\tfor (int y = 0; y < 12; y++) {
\t\tfor (int x = 0; x < 16; x++) {
\t\t\tfloat r = (float)x / 15.0f;
\t\t\tfloat g = (float)y / 11.0f;
\t\t\tfloat bl = 0.18f;
\t\t\ta.setPixel(x, y, r, g, bl, 1.0f);
\t\t\tb.setPixel(x, y, r, g, bl, 1.0f);
\t\t}
\t}
\tvar exactDiff = FloatImageDiff.compare(a, b);
\tExpect.isTrue(exactDiff.matches(1e-7), "identical FloatImages must match");
\tb.setPixel(4, 5, b.red(4, 5) + 0.05f, b.green(4, 5), b.blue(4, 5), 1.0f);
\tvar changedDiff = FloatImageDiff.compare(a, b);
\tExpect.isTrue(changedDiff.comparable, "diff must be comparable");
\tExpect.isTrue(Math.absDouble(changedDiff.maxAbsDiff - 0.05) < 1e-5, "maxAbsDiff should be 0.05");

\tImage rgba = a.toRGBA8(true);
\tFloatImage roundtrip = FloatImage.fromRGBA8(rgba, true);
\tvar srgbDiff = FloatImageDiff.compare(a, roundtrip);
\tExpect.isTrue(srgbDiff.maxAbsDiff < 0.01, "8-bit sRGB round-trip error must stay small");

\t/* 2. RawMosaic container checks. */
\tRawMosaic mosaic = RawMosaic(32, 24, 14, BAYER_RGGB);
\tmosaic.setBlackLevels(512.0f, 512.0f, 512.0f, 512.0f);
\tmosaic.setAsShotNeutral(0.5f, 1.0f, 0.7f);
\tmosaic.setSample(3, 4, (unsigned short)12345);
\tExpect.intEq((int)mosaic.sampleAt(3, 4), 12345, "RawMosaic sample round-trip");

\t/* 3. 12-bit 1-component lossless JPEG CFA bit-exact round-trip. */
\tint w12 = 64;
\tint h12 = 48;
\tArray<unsigned short> cfa12 = Array(w12 * h12);
\tfor (int y = 0; y < h12; y++) {
\t\tfor (int x = 0; x < w12; x++) {
\t\t\tint v = ((x * 53 + y * 97) ^ ((x & 1) * 1024) ^ ((y & 1) * 2048)) & 4095;
\t\t\tif (x == 0 && y == 0) { v = 0; }
\t\t\tif (x == w12 - 1 && y == h12 - 1) { v = 4095; }
\t\t\tcfa12.set(y * w12 + x, (unsigned short)v);
\t\t}
\t}
\tBytes enc12 = JPEG.encodeLossless16(w12, h12, 1, 12, cfa12);
\tvar dec12 = JPEG.decodeLossless16(enc12);
\tExpect.intEq(dec12.width, w12, "12-bit lossless width");
\tExpect.intEq(dec12.height, h12, "12-bit lossless height");
\tExpect.intEq(dec12.components, 1, "12-bit lossless components");
\tExpect.intEq(dec12.precision, 12, "12-bit lossless precision");
\tfor (int i = 0; i < w12 * h12; i++) {
\t\tExpect.intEq((int)dec12.samples.get(i), (int)cfa12.get(i), "12-bit lossless bit-exact");
\t}

\t/* 4. 14-bit 2-component DNG-style interleaved lossless JPEG CFA bit-exact round-trip. */
\tint w14 = 32;
\tint h14 = 48;
\tArray<unsigned short> cfa14 = Array(w14 * h14 * 2);
\tfor (int y = 0; y < h14; y++) {
\t\tfor (int x = 0; x < w14; x++) {
\t\t\tint v0 = (x * 419 + y * 211 + 512) & 16383;
\t\t\tint v1 = (16383 - ((x * 317 + y * 131) & 16383));
\t\t\tif (x == 5 && y == 5) { v0 = 0; v1 = 16383; }
\t\t\tcfa14.set((y * w14 + x) * 2, (unsigned short)v0);
\t\t\tcfa14.set((y * w14 + x) * 2 + 1, (unsigned short)v1);
\t\t}
\t}
\tBytes enc14 = JPEG.encodeLossless16(w14, h14, 2, 14, cfa14);
\tvar dec14 = JPEG.decodeLossless16(enc14);
\tExpect.intEq(dec14.width, w14, "14-bit lossless width");
\tExpect.intEq(dec14.height, h14, "14-bit lossless height");
\tExpect.intEq(dec14.components, 2, "14-bit lossless components");
\tExpect.intEq(dec14.precision, 14, "14-bit lossless precision");
\tfor (int i = 0; i < w14 * h14 * 2; i++) {
\t\tExpect.intEq((int)dec14.samples.get(i), (int)cfa14.get(i), "14-bit lossless bit-exact");
\t}

\t/* 5. 16-bit full-range lossless JPEG bit-exact round-trip (exercises SSSS == 16 / 32768 edge). */
\tint w16 = 32;
\tint h16 = 32;
\tArray<unsigned short> cfa16 = Array(w16 * h16);
\tfor (int y = 0; y < h16; y++) {
\t\tfor (int x = 0; x < w16; x++) {
\t\t\tint v = ((x & 1) == 0) ? (x * 2000 + y * 100) : (65535 - (x * 1500 + y * 200));
\t\t\tif (x == 10 && y == 10) { v = 0; }
\t\t\tif (x == 11 && y == 10) { v = 32768; }
\t\t\tif (x == 12 && y == 10) { v = 65535; }
\t\t\tcfa16.set(y * w16 + x, (unsigned short)(v & 65535));
\t\t}
\t}
\tBytes enc16 = JPEG.encodeLossless16(w16, h16, 1, 16, cfa16);
\tvar dec16 = JPEG.decodeLossless16(enc16);
\tExpect.intEq(dec16.precision, 16, "16-bit lossless precision");
\tfor (int i = 0; i < w16 * h16; i++) {
\t\tExpect.intEq((int)dec16.samples.get(i), (int)cfa16.get(i), "16-bit lossless bit-exact");
\t}

\tprint("PASS_FLOAT_AND_LOSSLESS_CFA\\n");
\treturn 0;
}
"""
    result = _run_btrc(native_project, native_compile, program, sanitize=sanitize)
    assert result.returncode == 0, f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    assert "PASS_FLOAT_AND_LOSSLESS_CFA" in result.stdout


@pytest.mark.parametrize("sanitize", [False, True])
def test_image_codec_roundtrips(native_project, native_compile, sanitize):
    program = """import Library.Bytes;
import Library.Image.FloatImage;
import Library.Image.ImageCodec;
import Library.Image.Pixels;
import Library.IO;
import Library.Math;
import Library.Testing;

int main() {
\t/* Build a 128x64 linear float test chart with 4 solid quadrants. */
\tFloatImage chart = FloatImage(128, 64);
\tfor (int y = 0; y < 64; y++) {
\t\tfor (int x = 0; x < 128; x++) {
\t\t\tif (x < 64 && y < 32) {
\t\t\t\t/* 16-bit precision test value: 0.180123 linear gray */
\t\t\t\tchart.setPixel(x, y, 0.180123f, 0.180123f, 0.180123f, 1.0f);
\t\t\t} else if (x >= 64 && y < 32) {
\t\t\t\tchart.setPixel(x, y, 0.75f, 0.10f, 0.05f, 1.0f);
\t\t\t} else if (x < 64 && y >= 32) {
\t\t\t\tchart.setPixel(x, y, 0.05f, 0.65f, 0.15f, 1.0f);
\t\t\t} else {
\t\t\t\tchart.setPixel(x, y, 0.08f, 0.20f, 0.85f, 1.0f);
\t\t\t}
\t\t}
\t}

\t/* 1. 16-bit linear TIFF round-trip proves >8-bit linear precision. */
\tBytes tiffBytes = ImageCodec.encode(chart, IMAGE_EXPORT_TIFF16, 100);
\tExpect.isTrue(tiffBytes.length() > 128 * 64 * 8, "TIFF16 byte length");
\tvar decodedTiff = ImageCodec.decodeLinear(tiffBytes, 0, false);
\tExpect.intEq(decodedTiff.image.width, 128, "TIFF16 width");
\tExpect.intEq(decodedTiff.image.height, 64, "TIFF16 height");
\tExpect.intEq(decodedTiff.originalWidth, 128, "TIFF16 originalWidth");
\tExpect.intEq(decodedTiff.originalHeight, 64, "TIFF16 originalHeight");
\tvar tiffDiff = FloatImageDiff.compare(chart, decodedTiff.image);
\tExpect.isTrue(tiffDiff.maxAbsDiff < 0.001, "TIFF16 linear round-trip must preserve >10-bit precision");

\t/* 2. PNG round-trip + hardware thumbnail downscale (maxEdge=32 -> 32x16). */
\tBytes pngBytes = ImageCodec.encode(chart, IMAGE_EXPORT_PNG, 100);
\tvar decodedPng = ImageCodec.decodeLinear(pngBytes, 0, false);
\tExpect.intEq(decodedPng.image.width, 128, "PNG width");
\tExpect.intEq(decodedPng.image.height, 64, "PNG height");
\tExpect.isTrue(Math.absDouble((double)decodedPng.image.red(16, 16) - 0.180123) < 0.015, "PNG gray patch");

\tImage thumbPng = ImageCodec.decodeRGBA8(pngBytes, 32);
\tExpect.intEq(thumbPng.width, 32, "PNG thumb width");
\tExpect.intEq(thumbPng.height, 16, "PNG thumb height");

\t/* 3. JPEG round-trip. */
\tBytes jpgBytes = ImageCodec.encode(chart, IMAGE_EXPORT_JPEG, 95);
\tvar decodedJpg = ImageCodec.decodeLinear(jpgBytes, 0, false);
\tExpect.intEq(decodedJpg.image.width, 128, "JPEG width");
\tExpect.intEq(decodedJpg.image.height, 64, "JPEG height");
\tExpect.isTrue(Math.absDouble((double)decodedJpg.image.red(96, 16) - 0.75) < 0.05, "JPEG red quadrant");
\tExpect.isTrue(Math.absDouble((double)decodedJpg.image.blue(96, 48) - 0.85) < 0.05, "JPEG blue quadrant");

\t/* 4. HEIC hardware encode + linear & Rec.2020 decode on Apple platforms. */
\tif (ImageCodec.supportsHEIC()) {
\t\tBytes heicBytes = ImageCodec.encode(chart, IMAGE_EXPORT_HEIC, 92);
\t\tExpect.isTrue(heicBytes.length() > 64, "HEIC encoded non-empty");
\t\tvar decodedHeic = ImageCodec.decodeLinear(heicBytes, 0, false);
\t\tExpect.intEq(decodedHeic.image.width, 128, "HEIC width");
\t\tExpect.intEq(decodedHeic.image.height, 64, "HEIC height");
\t\tExpect.isTrue(Math.absDouble((double)decodedHeic.image.red(16, 16) - 0.180123) < 0.04, "HEIC gray patch");
\t\tExpect.isTrue(Math.absDouble((double)decodedHeic.image.red(96, 16) - 0.75) < 0.08, "HEIC red patch");

\t\tvar decodedRec2020 = ImageCodec.decodeLinear(heicBytes, 64, true);
\t\tExpect.intEq(decodedRec2020.image.width, 64, "HEIC scaled Rec.2020 width");
\t\tExpect.intEq(decodedRec2020.image.height, 32, "HEIC scaled Rec.2020 height");
\t\tExpect.isTrue(decodedRec2020.isWideGamut, "Rec.2020 decode marks wide gamut");
\t}

\t/* 5. Foreground segmentation mask (Apple Vision + portable fallback) returns valid R8 matte. */
\tImage fgScene = Image(128, 128);
\tfor (int y = 0; y < 128; y++) {
\t\tfor (int x = 0; x < 128; x++) {
\t\t\tint dx = x - 64;
\t\t\tint dy = y - 64;
\t\t\tbool inside = (dx * dx + dy * dy) < 28 * 28;
\t\t\tfgScene.setPixel(x, y, inside ? RGBA(230, 80, 40, 255) : RGBA(24, 34, 48, 255));
\t\t}
\t}
\tBytes fgMask = ImageCodec.segmentForegroundMask(fgScene, 64, 64);
\tExpect.intEq(fgMask.length(), 64 * 64, "foreground mask has requested dimensions");
\tint centerVal = fgMask.get(32 * 64 + 32);
\tint cornerVal = fgMask.get(2 * 64 + 2);
\tExpect.isTrue(centerVal > cornerVal, "foreground mask highlights center subject over background");

\tprint("PASS_IMAGE_CODEC_ROUNDTRIPS\\n");
\treturn 0;
}
"""
    result = _run_btrc(native_project, native_compile, program, sanitize=sanitize)
    assert result.returncode == 0, f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    assert "PASS_IMAGE_CODEC_ROUNDTRIPS" in result.stdout
