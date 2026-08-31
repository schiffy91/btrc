#include "btrc_gpu_compute_internal.h"
#include <stddef.h>

bool btrc_gpu_available(void) { return false; }
void* btrc_gpu_acquire_compute(void) { return NULL; }
void* btrc_gpu_init_compute(void) { return NULL; }
void* btrc_gpu_create_buffer(void* gpu, int size, int usage) {
    (void)gpu; (void)size; (void)usage; return NULL;
}
void btrc_gpu_write_buffer(void* gpu, void* buffer, void* data, int size) {
    (void)gpu; (void)buffer; (void)data; (void)size;
}
void btrc_gpu_read_buffer(void* gpu, void* buffer, void* data, int size) {
    (void)gpu; (void)buffer; (void)data; (void)size;
}
bool btrc_gpu_read_buffer_checked(void* gpu, void* buffer,
        void* data, int size) {
    (void)gpu; (void)buffer; (void)data; (void)size; return false;
}
void btrc_gpu_buffer_destroy(void* buffer) { (void)buffer; }
void* btrc_gpu_create_shader(void* gpu, char* source) {
    (void)gpu; (void)source; return NULL;
}
void btrc_gpu_shader_destroy(void* shader) { (void)shader; }
void* btrc_gpu_create_compute_pipeline(void* gpu, void* shader, char* entry) {
    (void)gpu; (void)shader; (void)entry; return NULL;
}
void btrc_gpu_compute_pipeline_destroy(void* pipeline) { (void)pipeline; }
void* btrc_gpu_create_bind_group(void* gpu, void* pipeline,
        void** buffers, int count) {
    (void)gpu; (void)pipeline; (void)buffers; (void)count; return NULL;
}
void btrc_gpu_bind_group_destroy(void* group) { (void)group; }
bool btrc_gpu_dispatch(void* gpu, void* pipeline, void* group, int count) {
    (void)gpu; (void)pipeline; (void)group; (void)count;
    return false;
}
