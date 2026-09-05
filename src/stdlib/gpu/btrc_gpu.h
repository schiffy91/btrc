/*
 * btrc GPU Runtime — Simplified WebGPU C API
 *
 * Wraps the verbose webgpu.h API into simple functions callable from btrc.
 * Works with both wgpu-native and Dawn (both implement webgpu.h).
 *
 * The std.gpu boundary uses monotonic integer capabilities only. Native
 * pointers live in the separate compiler/runtime-only compute header. Owner
 * creation also returns a private one-time receipt required for teardown.
 */

#ifndef BTRC_GPU_H
#define BTRC_GPU_H

#include <stdbool.h>
#include <stdint.h>

_Static_assert(sizeof(unsigned long long) == sizeof(uint64_t),
    "std.gpu capabilities require a 64-bit unsigned long long");

enum {
    BTRC_GPU_ATTACH_READY = 0,
    BTRC_GPU_ATTACH_INVALID_SURFACE = 1,
    BTRC_GPU_ATTACH_SURFACE_BUSY = 2,
    BTRC_GPU_ATTACH_ADAPTER_UNAVAILABLE = 3,
    BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE = 4,
    BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED = 5,
    BTRC_GPU_ATTACH_OUT_OF_MEMORY = 6,
    BTRC_GPU_ATTACH_INTERNAL_ERROR = 7,
    BTRC_GPU_ATTACH_NOT_OWNER_THREAD = 8,
};

enum {
    BTRC_GPU_FRAME_READY = 100,
    BTRC_GPU_FRAME_PRESENTED = 101,
    BTRC_GPU_FRAME_TIMEOUT = 102,
    BTRC_GPU_FRAME_OUTDATED = 103,
    BTRC_GPU_FRAME_SURFACE_LOST = 104,
    BTRC_GPU_FRAME_OUT_OF_MEMORY = 105,
    BTRC_GPU_FRAME_DEVICE_LOST = 106,
    BTRC_GPU_FRAME_REJECTED = 107,
};

enum {
    BTRC_GPU_CLOSE_CLOSED = 200,
    BTRC_GPU_CLOSE_NOT_OWNER_THREAD = 201,
    BTRC_GPU_CLOSE_INVALID = 202,
};

enum {
    BTRC_GPU_RESOURCE_READY = 300,
    BTRC_GPU_RESOURCE_INVALID_GPU = 301,
    BTRC_GPU_RESOURCE_NOT_OWNER_THREAD = 302,
    BTRC_GPU_RESOURCE_DEVICE_LOST = 303,
    BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR = 304,
    BTRC_GPU_RESOURCE_INVALID_RESOURCE = 305,
    BTRC_GPU_RESOURCE_CREATION_FAILED = 306,
    BTRC_GPU_RESOURCE_OUT_OF_MEMORY = 307,
    BTRC_GPU_RESOURCE_INTERNAL_ERROR = 308,
};

enum {
    BTRC_GPU_DRAW_RECORDED = 400,
    BTRC_GPU_DRAW_INVALID_GPU = 401,
    BTRC_GPU_DRAW_NOT_OWNER_THREAD = 402,
    BTRC_GPU_DRAW_DEVICE_LOST = 403,
    BTRC_GPU_DRAW_INVALID_DESCRIPTOR = 404,
    BTRC_GPU_DRAW_INVALID_RESOURCE = 405,
    BTRC_GPU_DRAW_NO_ACTIVE_FRAME = 406,
    BTRC_GPU_DRAW_BACKEND_FAILURE = 407,
};

/* ---- GPU context attached to the sole std.app surface owner ---- */
int std_gpu_attach_surface(
    unsigned long long surface, unsigned long long* gpu_out,
    unsigned long long* owner_receipt_out);
char* std_gpu_status_message(int status);
int std_gpu_close(
    unsigned long long gpu, unsigned long long owner_receipt);
void std_gpu_finalize(
    unsigned long long gpu, unsigned long long owner_receipt);
int std_gpu_begin_frame(
    unsigned long long gpu, float r, float g, float b, float a);
int std_gpu_end_frame(unsigned long long gpu);

/* Public BTRC render resources use validated identities, never native handles.
 * Factories publish both output capabilities only with RESOURCE_READY and
 * leave both zero for every typed failure. */
int std_gpu_shader_create(
    unsigned long long gpu, char* wgsl_source,
    unsigned long long* shader_out,
    unsigned long long* owner_receipt_out);
int std_gpu_shader_destroy(
    unsigned long long shader, unsigned long long owner_receipt);
void std_gpu_shader_finalize(
    unsigned long long shader, unsigned long long owner_receipt);
int std_gpu_pipeline_create(
    unsigned long long gpu, unsigned long long shader,
    char* vertex_entry, char* fragment_entry,
    unsigned long long* pipeline_out,
    unsigned long long* owner_receipt_out);
int std_gpu_pipeline_destroy(
    unsigned long long pipeline, unsigned long long owner_receipt);
void std_gpu_pipeline_finalize(
    unsigned long long pipeline, unsigned long long owner_receipt);
int std_gpu_uniform_create(
    unsigned long long gpu, int float_count,
    unsigned long long* uniform_out,
    unsigned long long* owner_receipt_out);
int std_gpu_uniform_set(
    unsigned long long uniform, int index, float value);
int std_gpu_uniform_destroy(
    unsigned long long uniform, unsigned long long owner_receipt);
void std_gpu_uniform_finalize(
    unsigned long long uniform, unsigned long long owner_receipt);
int std_gpu_draw(
    unsigned long long gpu, unsigned long long pipeline, int vertex_count);
int std_gpu_draw_uniform(
    unsigned long long gpu, unsigned long long pipeline,
    int vertex_count, unsigned long long uniform);

/* Bounded native-UI display-list resource. It records into the active frame
 * of the supplied GPU capability and cannot create/acquire/present a surface. */
int std_gpu_native_ui_create(
    unsigned long long gpu,
    unsigned long long* compositor_out,
    unsigned long long* owner_receipt_out);
int std_gpu_native_ui_begin(
    unsigned long long compositor, int logical_width, int logical_height);
int std_gpu_native_ui_add_rect(
    unsigned long long compositor,
    float x, float y, float width, float height,
    float red, float green, float blue, float alpha, float radius);
int std_gpu_native_ui_add_glyph(
    unsigned long long compositor,
    float x, float y, float width, float height,
    float red, float green, float blue, float alpha,
    unsigned long long glyph_bits);
int std_gpu_native_ui_system_typography_available(
    unsigned long long compositor);
int std_gpu_native_ui_measure_text(
    unsigned long long compositor,
    char* text,
    int font_size,
    int line_height,
    int font_weight,
    int* width_out,
    int* height_out,
    int* ascent_out,
    int* descent_out,
    int* advance_out);
/* Rasterize one system-font text run for the caller's own std.image. The
 * result is a tightly packed top-down RGBA8 raster, R=G=B=255 with straight
 * alpha coverage, so the caller tints it. Width and height are backing
 * pixels (ceil(logical * backing_scale), each clamped to 1..4096). Release
 * *rgba_out with std_gpu_native_ui_release_text_bitmap. */
int std_gpu_native_ui_rasterize_text(
    unsigned long long compositor,
    char* text,
    int font_size,
    int line_height,
    int font_weight,
    float backing_scale,
    int* width_out,
    int* height_out,
    void** rgba_out,
    unsigned long long* rgba_bytes_out);
void std_gpu_native_ui_release_text_bitmap(void* rgba);
int std_gpu_native_ui_add_text(
    unsigned long long compositor,
    char* text,
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
int std_gpu_native_ui_add_image(
    unsigned long long compositor,
    char* identity,
    unsigned char* rgba,
    int source_width,
    int source_height,
    unsigned long long source_revision,
    float x,
    float y,
    float width,
    float height);
int std_gpu_native_ui_draw(
    unsigned long long gpu, unsigned long long compositor);
int std_gpu_native_ui_destroy(
    unsigned long long compositor, unsigned long long owner_receipt);
void std_gpu_native_ui_finalize(
    unsigned long long compositor, unsigned long long owner_receipt);
int std_gpu_native_ui_command_count(unsigned long long compositor);
int std_gpu_native_ui_image_count(unsigned long long compositor);

#endif /* BTRC_GPU_H */
