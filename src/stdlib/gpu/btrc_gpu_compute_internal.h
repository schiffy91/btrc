/* Compiler/runtime-only raw WebGPU compute ABI.
 *
 * Source programs use the capability-only std.gpu API from btrc_gpu.h.  The
 * compiler includes this header solely for generated @gpu dispatch helpers;
 * native pointers must never cross the public std.gpu surface boundary.
 */
#ifndef BTRC_GPU_COMPUTE_INTERNAL_H
#define BTRC_GPU_COMPUTE_INTERNAL_H

#include "btrc_gpu.h"

void btrc_gpu_destroy(void* gpu);

void* btrc_gpu_create_shader(void* gpu, char* wgsl_source);
void btrc_gpu_shader_destroy(void* shader);

void* btrc_gpu_create_render_pipeline(
    void* gpu, void* shader, char* vertex_entry, char* fragment_entry);
void btrc_gpu_pipeline_destroy(void* pipeline);

bool btrc_gpu_begin_frame(void* gpu, float r, float g, float b, float a);
void btrc_gpu_draw(void* gpu, void* pipeline, int vertex_count);
void btrc_gpu_end_frame(void* gpu);

bool btrc_gpu_available(void);
void* btrc_gpu_init_compute(void);
void* btrc_gpu_acquire_compute(void);

void* btrc_gpu_create_buffer(void* gpu, int size, int usage);
void btrc_gpu_write_buffer(void* gpu, void* buf, void* data, int size);
bool btrc_gpu_read_buffer_checked(
    void* gpu, void* buf, void* dst, int size);
void btrc_gpu_read_buffer(void* gpu, void* buf, void* dst, int size);
void btrc_gpu_buffer_destroy(void* buf);

void* btrc_gpu_create_compute_pipeline(
    void* gpu, void* shader, char* entry);
void btrc_gpu_compute_pipeline_destroy(void* pipeline);

void* btrc_gpu_create_bind_group(
    void* gpu, void* pipeline, void** buffers, int count);
void btrc_gpu_bind_group_destroy(void* bg);
bool btrc_gpu_dispatch(
    void* gpu, void* pipeline, void* bg, int workgroups_x);

void* btrc_gpu_create_uniform(void* gpu, int float_count);
void btrc_gpu_set_uniform(void* uniform, int index, float value);
void btrc_gpu_upload_uniform(void* gpu, void* uniform);
bool btrc_gpu_draw_uniform(
    void* gpu, void* pipeline, int vertex_count, void* uniform);
void btrc_gpu_uniform_destroy(void* uniform);

#define BTRC_GPU_STORAGE  0x80
#define BTRC_GPU_UNIFORM  0x40
#define BTRC_GPU_COPY_DST 0x08
#define BTRC_GPU_COPY_SRC 0x04

#endif /* BTRC_GPU_COMPUTE_INTERNAL_H */
