/* Compiler/runtime-only raw WebGPU compute ABI.
 *
 * The compiler includes this header solely for generated @gpu dispatch
 * helpers. Portable GUI/GPU rendering uses typed native SDK imports instead.
 */
#ifndef BTRC_GPU_COMPUTE_INTERNAL_H
#define BTRC_GPU_COMPUTE_INTERNAL_H

#include <stdbool.h>
#include <stdint.h>

void btrc_gpu_destroy(void* gpu);

void* btrc_gpu_create_shader(void* gpu, char* wgsl_source);
void btrc_gpu_shader_destroy(void* shader);

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

#define BTRC_GPU_STORAGE  0x80
#define BTRC_GPU_UNIFORM  0x40
#define BTRC_GPU_COPY_DST 0x08
#define BTRC_GPU_COPY_SRC 0x04

#endif /* BTRC_GPU_COMPUTE_INTERNAL_H */
