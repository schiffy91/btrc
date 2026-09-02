#include "btrc_gpu_native_ui_text_internal.h"

#include <assert.h>
#include <stddef.h>
#include <stdio.h>

static size_t alpha_sum(
        const BtrcNativeUiTextBitmap* bitmap,
        int first_row,
        int row_count) {
    size_t sum = 0;
    int last_row = first_row + row_count;
    for (int row = first_row; row < last_row; ++row) {
        for (int column = 0; column < bitmap->width; ++column) {
            size_t pixel = (size_t)row * (size_t)bitmap->width +
                (size_t)column;
            sum += bitmap->rgba[pixel * 4u + 3u];
        }
    }
    return sum;
}

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

    BtrcNativeUiTextBitmap asymmetric;
    assert(btrc_gpu_native_ui_text_rasterize(
        "F", 64, 80, 600, 1.0f, &asymmetric));
    size_t upper_alpha = alpha_sum(&asymmetric, 0, asymmetric.height / 2);
    size_t lower_alpha = alpha_sum(
        &asymmetric,
        asymmetric.height / 2,
        asymmetric.height - asymmetric.height / 2);
    assert(upper_alpha > lower_alpha);
    btrc_gpu_native_ui_text_bitmap_release(&asymmetric);

    puts("PASS: macOS system typography provider");
    return 0;
}
