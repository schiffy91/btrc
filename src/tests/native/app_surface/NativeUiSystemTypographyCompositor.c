#include "btrc_gpu_native_ui_internal.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static uint64_t alpha_sum(
        const unsigned char* rgba,
        int width,
        int first_row,
        int row_count) {
    uint64_t sum = 0;
    int last_row = first_row + row_count;
    for (int row = first_row; row < last_row; ++row) {
        for (int column = 0; column < width; ++column) {
            size_t pixel = (size_t)row * (size_t)width + (size_t)column;
            sum += rgba[pixel * 4u + 3u];
        }
    }
    return sum;
}

int main(void) {
    void* compositor = btrc_gpu_native_ui_create(
        (WGPUDevice)(uintptr_t)1,
        (WGPUQueue)(uintptr_t)1,
        WGPUTextureFormat_RGBA8Unorm);
    assert(compositor != NULL);
    assert(btrc_gpu_native_ui_begin(compositor, 640, 480));

    BtrcNativeUiTextMetrics metrics;
    assert(btrc_gpu_native_ui_measure_text(
        compositor, "BTRSmith", 24, 30, 400, &metrics));
    assert(metrics.width > 0 && metrics.height == 30);
    assert(btrc_gpu_native_ui_add_text(
        compositor,
        "F",
        10.0f,
        12.0f,
        64,
        80,
        600,
        1.0f,
        0.1f,
        0.2f,
        0.3f,
        1.0f));
    const unsigned char* uploaded = NULL;
    int uploaded_width = 0;
    int uploaded_height = 0;
    assert(btrc_gpu_native_ui_test_last_upload(
        compositor, &uploaded, &uploaded_width, &uploaded_height));
    assert(uploaded_width > 0 && uploaded_height == 80);
    uint64_t upper_alpha = alpha_sum(
        uploaded, uploaded_width, 0, uploaded_height / 2);
    uint64_t lower_alpha = alpha_sum(
        uploaded,
        uploaded_width,
        uploaded_height / 2,
        uploaded_height - uploaded_height / 2);
    assert(upper_alpha > lower_alpha);
    assert(btrc_gpu_native_ui_add_text(
        compositor,
        "F",
        100.0f,
        12.0f,
        64,
        80,
        600,
        1.0f,
        0.8f,
        0.7f,
        0.6f,
        1.0f));
    assert(btrc_gpu_native_ui_image_count(compositor) == 1);
    assert(btrc_gpu_native_ui_test_upload_count() == 1);
    assert(btrc_gpu_native_ui_test_placement_count(compositor) == 2);
    assert(!btrc_gpu_native_ui_add_text(
        compositor,
        "BTRSmith",
        10.0f,
        12.0f,
        24,
        30,
        400,
        0.0f,
        0.1f,
        0.2f,
        0.3f,
        1.0f));
    assert(btrc_gpu_native_ui_draw(
        compositor, (WGPURenderPassEncoder)(uintptr_t)1));

    assert(btrc_gpu_native_ui_begin(compositor, 640, 480));
    assert(btrc_gpu_native_ui_add_text(
        compositor,
        "F",
        10.0f,
        12.0f,
        64,
        80,
        600,
        1.0f,
        0.1f,
        0.2f,
        0.3f,
        1.0f));
    assert(btrc_gpu_native_ui_test_upload_count() == 1);
    assert(btrc_gpu_native_ui_add_text(
        compositor,
        "F",
        10.0f,
        50.0f,
        64,
        80,
        700,
        1.0f,
        0.1f,
        0.2f,
        0.3f,
        1.0f));
    assert(btrc_gpu_native_ui_image_count(compositor) == 2);
    assert(btrc_gpu_native_ui_test_upload_count() == 2);

    btrc_gpu_native_ui_destroy(compositor);
    puts("PASS: macOS system typography compositor");
    return 0;
}
