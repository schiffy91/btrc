#include "btrc_gpu_native_ui_internal.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

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
        "BTRSmith",
        10.0f,
        12.0f,
        24,
        30,
        400,
        2.0f,
        0.1f,
        0.2f,
        0.3f,
        1.0f));
    assert(btrc_gpu_native_ui_add_text(
        compositor,
        "BTRSmith",
        100.0f,
        12.0f,
        24,
        30,
        400,
        2.0f,
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
        "BTRSmith",
        10.0f,
        12.0f,
        24,
        30,
        400,
        2.0f,
        0.1f,
        0.2f,
        0.3f,
        1.0f));
    assert(btrc_gpu_native_ui_test_upload_count() == 1);
    assert(btrc_gpu_native_ui_add_text(
        compositor,
        "BTRSmith",
        10.0f,
        50.0f,
        24,
        30,
        700,
        2.0f,
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
