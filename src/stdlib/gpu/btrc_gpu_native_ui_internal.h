#ifndef BTRC_GPU_NATIVE_UI_INTERNAL_H
#define BTRC_GPU_NATIVE_UI_INTERNAL_H

#include <stdbool.h>
#include <stdint.h>
#include <webgpu.h>

#include "btrc_gpu_native_ui_text_internal.h"

/* Private std.native_ui compositor. The device, queue, format, and active
 * render pass are borrowed from the one std.gpu owner; this layer cannot
 * create or present a window, surface, adapter, or device. */
void* btrc_gpu_native_ui_create(
    WGPUDevice device, WGPUQueue queue, WGPUTextureFormat surface_format);
void btrc_gpu_native_ui_destroy(void* compositor);

bool btrc_gpu_native_ui_begin(
    void* compositor, int logical_width, int logical_height);
bool btrc_gpu_native_ui_add_rect(
    void* compositor,
    float x, float y, float width, float height,
    float red, float green, float blue, float alpha,
    float radius);
bool btrc_gpu_native_ui_add_glyph(
    void* compositor,
    float x, float y, float width, float height,
    float red, float green, float blue, float alpha,
    uint64_t glyph_bits);
bool btrc_gpu_native_ui_add_image(
    void* compositor,
    const char* identity,
    const unsigned char* rgba,
    int source_width,
    int source_height,
    uint64_t source_revision,
    float x,
    float y,
    float width,
    float height);
bool btrc_gpu_native_ui_measure_text(
    void* compositor,
    const char* text,
    int font_size,
    int line_height,
    int font_weight,
    BtrcNativeUiTextMetrics* metrics_out);
bool btrc_gpu_native_ui_add_text(
    void* compositor,
    const char* text,
    float x,
    float y,
    int font_size,
    int line_height,
    int font_weight,
    float backing_scale,
    float red,
    float green,
    float blue,
    float alpha);
bool btrc_gpu_native_ui_draw(
    void* compositor, WGPURenderPassEncoder active_pass);

int btrc_gpu_native_ui_command_count(void* compositor);
int btrc_gpu_native_ui_image_count(void* compositor);

#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
void btrc_gpu_native_ui_test_fail_next_create(void);
void btrc_gpu_native_ui_test_fail_next_upload(void);
int btrc_gpu_native_ui_test_upload_count(void);
int btrc_gpu_native_ui_test_placement_count(void* compositor);
uint64_t btrc_gpu_native_ui_test_cached_pixels(void* compositor);
/* The returned snapshot is borrowed until the next upload or compositor
 * destruction. */
bool btrc_gpu_native_ui_test_last_upload(
    void* compositor,
    const unsigned char** rgba_out,
    int* width_out,
    int* height_out);
bool btrc_gpu_native_ui_test_has_image(
    void* compositor, const char* identity);
#endif

#endif
