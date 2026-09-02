#include "btrc_gpu_native_ui_text_internal.h"

#include <assert.h>
#include <stddef.h>
#include <stdio.h>

int main(void) {
    assert(btrc_gpu_native_ui_text_available());

    BtrcNativeUiTextMetrics narrow;
    BtrcNativeUiTextMetrics wide;
    BtrcNativeUiTextMetrics heading;
    assert(btrc_gpu_native_ui_text_measure("iiii", 24, 30, 400, &narrow));
    assert(btrc_gpu_native_ui_text_measure("WWWW", 24, 30, 400, &wide));
    assert(btrc_gpu_native_ui_text_measure(
        "BTRSmith \xe2\x99\xaa", 24, 30, 600, &heading));
    assert(narrow.width > 0 && wide.width > narrow.width);
    assert(heading.width > 0 && heading.height == 30);
    assert(heading.ascent > 0 && heading.descent >= 0);
    assert(heading.ascent + heading.descent <= heading.height);
    assert(heading.advance > 0);
    BtrcNativeUiTextMetrics invalid;
    assert(!btrc_gpu_native_ui_text_measure(
        "\xc3", 24, 30, 400, &invalid));

    BtrcNativeUiTextBitmap bitmap;
    assert(btrc_gpu_native_ui_text_rasterize(
        "BTRSmith \xe2\x99\xaa", 24, 30, 600, 2.0f, &bitmap));
    assert(bitmap.rgba != NULL);
    assert(bitmap.width >= heading.width * 2);
    assert(bitmap.height == 60);
    size_t opaque = 0;
    size_t antialiased = 0;
    size_t pixels = (size_t)bitmap.width * (size_t)bitmap.height;
    for (size_t index = 0; index < pixels; ++index) {
        unsigned char alpha = bitmap.rgba[index * 4u + 3u];
        if (alpha != 0u) { opaque++; }
        if (alpha != 0u && alpha != 255u) { antialiased++; }
        assert(bitmap.rgba[index * 4u + 0u] == 255u);
        assert(bitmap.rgba[index * 4u + 1u] == 255u);
        assert(bitmap.rgba[index * 4u + 2u] == 255u);
    }
    assert(opaque > 0);
    assert(antialiased > 0);
    btrc_gpu_native_ui_text_bitmap_release(&bitmap);
    assert(bitmap.rgba == NULL && bitmap.width == 0 && bitmap.height == 0);

    puts("PASS: macOS system typography provider");
    return 0;
}
