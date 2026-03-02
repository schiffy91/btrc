/*
 * btrc GPU Runtime — Simplified WebGPU C API
 *
 * Wraps the verbose webgpu.h API into simple functions callable from btrc.
 * Works with both wgpu-native and Dawn (both implement webgpu.h).
 *
 * All handles are void* for btrc compatibility.
 */

#ifndef BTRC_GPU_H
#define BTRC_GPU_H

#include <stdbool.h>
#include <stdint.h>

/* ---- Window ---- */
void* btrc_gpu_window_create(char* title, int width, int height);
bool  btrc_gpu_window_is_open(void* win);
void  btrc_gpu_window_poll(void* win);
int   btrc_gpu_window_width(void* win);
int   btrc_gpu_window_height(void* win);
void  btrc_gpu_window_destroy(void* win);

/* ---- GPU context ---- */
void* btrc_gpu_init(void* win);
void  btrc_gpu_destroy(void* gpu);

/* ---- Shaders ---- */
void* btrc_gpu_create_shader(void* gpu, char* wgsl_source);
void  btrc_gpu_shader_destroy(void* shader);

/* ---- Render Pipeline ---- */
void* btrc_gpu_create_render_pipeline(
    void* gpu, void* shader,
    char* vertex_entry, char* fragment_entry);
void btrc_gpu_pipeline_destroy(void* pipeline);

/* ---- Frame rendering ---- */
bool btrc_gpu_begin_frame(void* gpu, float r, float g, float b, float a);
void btrc_gpu_draw(void* gpu, void* pipeline, int vertex_count);
void btrc_gpu_end_frame(void* gpu);

/* ---- Headless compute ---- */
void* btrc_gpu_init_compute(void);

/* ---- Buffers ---- */
void* btrc_gpu_create_buffer(void* gpu, int size, int usage);
void  btrc_gpu_write_buffer(void* gpu, void* buf, void* data, int size);
void  btrc_gpu_read_buffer(void* gpu, void* buf, void* dst, int size);
void  btrc_gpu_buffer_destroy(void* buf);

/* ---- Compute pipeline ---- */
void* btrc_gpu_create_compute_pipeline(void* gpu, void* shader, char* entry);
void  btrc_gpu_compute_pipeline_destroy(void* pipeline);

/* ---- Bind group ---- */
void* btrc_gpu_create_bind_group(void* gpu, void* pipeline,
                                  void** buffers, int count);
void  btrc_gpu_bind_group_destroy(void* bg);

/* ---- Dispatch ---- */
void  btrc_gpu_dispatch(void* gpu, void* pipeline, void* bg, int workgroups_x);

/* ---- Buffer usage flags ---- */
#define BTRC_GPU_STORAGE  0x80
#define BTRC_GPU_UNIFORM  0x40
#define BTRC_GPU_COPY_DST 0x08
#define BTRC_GPU_COPY_SRC 0x04

#endif /* BTRC_GPU_H */
