#include "btrc_gpu_native_ui_internal.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static void add(
        void* compositor,
        const char* identity,
        unsigned char* pixels,
        int width,
        int height,
        uint64_t revision,
        float x) {
    bool added = btrc_gpu_native_ui_add_image(
        compositor,
        identity,
        pixels,
        width,
        height,
        revision,
        x,
        0.0f,
        8.0f,
        8.0f);
    if (!added) { fprintf(stderr, "failed to add image %s\n", identity); }
    assert(added);
}

int main(void) {
    unsigned char pixels_a[8] = { 0 };
    unsigned char pixels_b[8] = { 0 };
    unsigned char pixels_c[8] = { 0 };
    unsigned char pixels_d[24] = { 0 };
    unsigned char pixels_e[32] = { 0 };
    unsigned char pixels_p[4] = { 0 };
    void* compositor = btrc_gpu_native_ui_create(
        (WGPUDevice)(uintptr_t)1,
        (WGPUQueue)(uintptr_t)1,
        WGPUTextureFormat_RGBA8Unorm);
    assert(compositor != NULL);

    /* Fill a three-slot/six-pixel test cache. */
    assert(btrc_gpu_native_ui_begin(compositor, 64, 64));
    add(compositor, "a", pixels_a, 1, 2, 1, 0.0f);
    add(compositor, "b", pixels_b, 1, 2, 1, 8.0f);
    add(compositor, "c", pixels_c, 1, 2, 1, 16.0f);
    assert(btrc_gpu_native_ui_image_count(compositor) == 3);
    assert(btrc_gpu_native_ui_test_cached_pixels(compositor) == 6);
    assert(btrc_gpu_native_ui_test_upload_count() == 3);

    /* Mark the last dense slot current, then add a six-pixel image. This
     * requires two old entries to be evicted and compacts the current entry;
     * its earlier draw placement must follow the moved slot. */
    assert(btrc_gpu_native_ui_begin(compositor, 64, 64));
    add(compositor, "c", pixels_c, 1, 2, 1, 16.0f);
    add(compositor, "d", pixels_d, 3, 2, 1, 24.0f);
    assert(btrc_gpu_native_ui_image_count(compositor) == 2);
    assert(btrc_gpu_native_ui_test_cached_pixels(compositor) == 8);
    assert(btrc_gpu_native_ui_test_has_image(compositor, "d"));
    assert(btrc_gpu_native_ui_test_upload_count() == 4);
    assert(btrc_gpu_native_ui_draw(
        compositor, (WGPURenderPassEncoder)(uintptr_t)1));

    /* Candidate creation and upload failures leave the old cache untouched,
     * so retry can replace atomically and perform all required evictions. */
    assert(btrc_gpu_native_ui_begin(compositor, 64, 64));
    btrc_gpu_native_ui_test_fail_next_create();
    assert(!btrc_gpu_native_ui_add_image(
        compositor, "e", pixels_e, 4, 2, 1,
        0.0f, 0.0f, 8.0f, 8.0f));
    assert(btrc_gpu_native_ui_image_count(compositor) == 2);
    assert(btrc_gpu_native_ui_test_cached_pixels(compositor) == 8);
    assert(!btrc_gpu_native_ui_test_has_image(compositor, "e"));
    assert(btrc_gpu_native_ui_test_upload_count() == 4);

    btrc_gpu_native_ui_test_fail_next_upload();
    assert(!btrc_gpu_native_ui_add_image(
        compositor, "e", pixels_e, 4, 2, 1,
        0.0f, 0.0f, 8.0f, 8.0f));
    assert(btrc_gpu_native_ui_image_count(compositor) == 2);
    assert(btrc_gpu_native_ui_test_cached_pixels(compositor) == 8);
    assert(!btrc_gpu_native_ui_test_has_image(compositor, "e"));

    add(compositor, "e", pixels_e, 4, 2, 1, 0.0f);
    assert(btrc_gpu_native_ui_image_count(compositor) == 1);
    assert(btrc_gpu_native_ui_test_cached_pixels(compositor) == 8);
    assert(btrc_gpu_native_ui_test_has_image(compositor, "e"));
    assert(btrc_gpu_native_ui_test_upload_count() == 5);

    /* Explicit revision is the replacement signal for in-place mutations. */
    assert(btrc_gpu_native_ui_begin(compositor, 64, 64));
    add(compositor, "e", pixels_e, 4, 2, 1, 0.0f);
    assert(btrc_gpu_native_ui_test_upload_count() == 5);
    assert(btrc_gpu_native_ui_begin(compositor, 64, 64));
    add(compositor, "e", pixels_e, 4, 2, 2, 8.0f);
    assert(btrc_gpu_native_ui_test_upload_count() == 6);

    /* An unchanged identity/revision/dimension tuple is placed twice but
     * uploaded only once; each placement retains its own rectangle. */
    assert(btrc_gpu_native_ui_begin(compositor, 64, 64));
    add(compositor, "p", pixels_p, 1, 1, 1, 3.0f);
    add(compositor, "p", pixels_p, 1, 1, 1, 33.0f);
    assert(btrc_gpu_native_ui_test_placement_count(compositor) == 2);
    assert(btrc_gpu_native_ui_test_upload_count() == 7);

    btrc_gpu_native_ui_destroy(compositor);
    puts("PASS: native UI cache policy");
    return 0;
}
