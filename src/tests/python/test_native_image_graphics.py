"""ImageIO and CoreGraphics: real PNG data, dictionary options and rendered pixels."""

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import run_native_executable


@pytest.mark.parametrize("sanitized", [False, True])
def test_imageio_borrowed_result_owned_after_source_release(native_project, native_compile, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#include <ImageIO/ImageIO.h>\n")
    (source.parent / "Foundation.btrc").write_text("// Actual ImageIO and Core Foundation declarations.\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "borrowedImageIO"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["CGImageSourceRef", "CFDataRef", "CFStringRef", "CGImageSourceCreateWithData", "CGImageSourceCreateIncremental", "CGImageSourceGetType", "CFDataCreate", "CFStringGetLength", "CFStringGetCString", "CFRetain", "CFRelease", "kCFStringEncodingUTF8"]
owned-results = ["CFDataCreate", "CGImageSourceCreateWithData", "CGImageSourceCreateIncremental"]
borrowed-parameters = ["CGImageSourceCreateWithData.data", "CGImageSourceGetType.isrc", "CFStringGetLength.theString", "CFStringGetCString.theString"]
[native.bindings.borrowed-results]
CGImageSourceGetType = "isrc"
[native.bindings.resources.CGImageSourceRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
[native.bindings.resources.CFDataRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
[native.bindings.resources.CFStringRef]
ownership = "reference-counted"
retain = "CFRetain"
release = "CFRelease"
""")
    source.write_text(r"""import ./Foundation.btrc;
#include <assert.h>
#include <string.h>
int main() {
    unsigned char pixels[34] = {0x47,0x49,0x46,0x38,0x39,0x61,1,0,1,0,0x80,0,0,0,0,0,0xff,0xff,0xff,0x2c,0,0,0,0,1,0,1,0,0,2,1,0x4c,0,0x3b};
    for (int index = 0; index < 128; index++) {
        var empty = CGImageSourceCreateIncremental(null); assert(empty != null);
        assert(CGImageSourceGetType(empty) == null); release empty;
        var data = CFDataCreate(null, pixels, 34L); assert(data != null);
        var source = CGImageSourceCreateWithData(data, null); assert(source != null);
        var type = CGImageSourceGetType(source); assert(type != null);
        release data; release source;
        var alias = type; release type;
        assert(CFStringGetLength(alias) == 18L);
        char name[64];
        assert(CFStringGetCString(alias, name, 64L, kCFStringEncodingUTF8));
        assert(strcmp(name, "com.compuserve.gif") == 0);
    }
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitized, frameworks=("CoreFoundation", "ImageIO"))


@pytest.mark.parametrize("sanitized", [False, True])
def test_imageio_options_use_real_sdk_keys_and_dictionary_callbacks(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFDictionaryCreateMutable", "CFDictionarySetValue", "CFDictionaryGetValue", "CFRelease", '
            '"kCFAllocatorDefault", "kCFTypeDictionaryKeyCallBacks", "kCFTypeDictionaryValueCallBacks", '
            '"kCGImageSourceShouldCache", "kCFBooleanFalse"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#include <CoreFoundation/CoreFoundation.h>\n#include <ImageIO/ImageIO.h>\n",
        encoding="utf-8",
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        "\tvar options = CFDictionaryCreateMutable(kCFAllocatorDefault, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);\n"
        "\tif (options == null) { return 1; }\n"
        "\tCFDictionarySetValue(options, kCGImageSourceShouldCache, kCFBooleanFalse);\n"
        "\tbool correct = CFDictionaryGetValue(options, kCGImageSourceShouldCache) == kCFBooleanFalse;\n"
        "\tCFRelease(options);\n"
        "\treturn correct ? 0 : 2;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, ("CoreFoundation", "ImageIO"))


@pytest.mark.parametrize("sanitized", [False, True])
def test_coregraphics_nullable_context_renders_real_pixels(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CGColorSpaceCreateDeviceRGB", "CFRelease", "CGBitmapContextCreate", "CGContextRelease", '
            '"CGContextSetRGBFillColor", "CGContextFillRect", "CGRectMake", "kCGImageAlphaPremultipliedLast", "kCGBitmapByteOrder32Big"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#include <CoreFoundation/CoreFoundation.h>\n#include <CoreGraphics/CoreGraphics.h>\n", encoding="utf-8"
    )
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        "\tunsigned char pixels[16] = {0};\n"
        "\tvar colorSpace = CGColorSpaceCreateDeviceRGB();\n"
        "\tif (colorSpace == null) { return 1; }\n"
        "\tvar context = CGBitmapContextCreate(pixels, 2, 2, 8, 8, colorSpace, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);\n"
        "\tCFRelease(colorSpace);\n"
        "\tif (context == null) { return 2; }\n"
        "\tCGContextSetRGBFillColor(context, 1.0, 0.0, 0.0, 1.0);\n"
        "\tCGContextFillRect(context, CGRectMake(0.0, 0.0, 2.0, 2.0));\n"
        "\tCGContextRelease(context);\n"
        "\tfor (int index = 0; index < 16; index += 4) {\n"
        "\t\tif (pixels[index] != 255 || pixels[index + 1] != 0 || pixels[index + 2] != 0 || pixels[index + 3] != 255) { return 3; }\n"
        "\t}\n\treturn 0;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, ("CoreFoundation", "CoreGraphics"))


@pytest.mark.parametrize("sanitized", [False, True])
def test_imageio_nonnull_data_and_nullable_source_execute_real_png(native_project, native_compile, tmp_path, sanitized):
    source, sdk, triple = native_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"',
            '"CFDataCreate", "CFRelease", "CGImageSourceCreateWithData", "CGImageSourceGetCount"',
        ),
        encoding="utf-8",
    )
    (root / "Foundation.h").write_text(
        "#include <CoreFoundation/CoreFoundation.h>\n#include <ImageIO/ImageIO.h>\n", encoding="utf-8"
    )
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000200000002080600000072b60d240000001549444154789c63f8cfc0f01f081b18c0f4ffff0e003f1807ba237f62e60000000049454e44ae426082"
    )
    data = ", ".join(str(value) for value in png)
    (source.parent / "Foundation.btrc").write_text(
        "int verifyFoundation() {\n"
        f"\tunsigned char png[{len(png)}] = {{{data}}};\n"
        f"\tvar data = CFDataCreate(null, png, {len(png)});\n"
        "\tif (data == null) { return 1; }\n"
        "\tvar image = CGImageSourceCreateWithData(data, null);\n"
        "\tCFRelease(data);\n"
        "\tif (image == null) { return 2; }\n"
        "\tvar count = CGImageSourceGetCount(image);\n"
        "\tCFRelease(image);\n"
        "\treturn count == 1 ? 0 : 3;\n}\n",
        encoding="utf-8",
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert "__btrc_native_CGImageSourceCreateWithData" in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, ("CoreFoundation", "ImageIO"))
