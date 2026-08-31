#include "btrc_gpu_compute_internal.h"

#include <stdlib.h>
#include <string.h>

#ifndef STUB_STATUS_CODE
#define STUB_STATUS_CODE 0
#endif
#ifndef STUB_FAIL_READBACK
#define STUB_FAIL_READBACK 0
#endif
#ifndef STUB_DISPATCH_FAIL
#define STUB_DISPATCH_FAIL 0
#endif

typedef struct StubBuffer {
    unsigned char* data;
    int size;
} StubBuffer;

static StubBuffer* status_buffer;

bool btrc_gpu_available(void) { return true; }
void* btrc_gpu_acquire_compute(void) {
    static int singleton;
    return &singleton;
}
void* btrc_gpu_init_compute(void) { return malloc(1); }
void* btrc_gpu_create_buffer(void* gpu, int size, int usage) {
    (void)gpu; (void)usage;
    StubBuffer* buffer = malloc(sizeof(*buffer));
    if (buffer == NULL) { return NULL; }
    buffer->size = size;
    buffer->data = calloc((size_t)size, 1);
    return buffer;
}
void btrc_gpu_write_buffer(void* gpu, void* raw, void* data, int size) {
    (void)gpu;
    StubBuffer* buffer = raw;
    if (buffer != NULL && data != NULL && size <= buffer->size) {
        memcpy(buffer->data, data, (size_t)size);
    }
}
bool btrc_gpu_read_buffer_checked(void* gpu, void* raw, void* data, int size) {
    (void)gpu;
    if (STUB_FAIL_READBACK) { return false; }
    StubBuffer* buffer = raw;
    if (buffer == NULL || data == NULL || size > buffer->size) { return false; }
    memcpy(data, buffer->data, (size_t)size);
    return true;
}
void btrc_gpu_read_buffer(void* gpu, void* raw, void* data, int size) {
    (void)btrc_gpu_read_buffer_checked(gpu, raw, data, size);
}
void btrc_gpu_buffer_destroy(void* raw) {
    StubBuffer* buffer = raw;
    if (buffer == NULL) { return; }
    free(buffer->data);
    free(buffer);
}
void* btrc_gpu_create_shader(void* gpu, char* source) {
    (void)gpu; (void)source; return malloc(1);
}
void btrc_gpu_shader_destroy(void* shader) { free(shader); }
void* btrc_gpu_create_compute_pipeline(void* gpu, void* shader, char* entry) {
    (void)gpu; (void)shader; (void)entry; return malloc(1);
}
void btrc_gpu_compute_pipeline_destroy(void* pipeline) { free(pipeline); }
void* btrc_gpu_create_bind_group(void* gpu, void* pipeline,
        void** buffers, int count) {
    (void)gpu; (void)pipeline;
    if (count > 0) { status_buffer = buffers[count - 1]; }
    return malloc(1);
}
void btrc_gpu_bind_group_destroy(void* group) { free(group); }
bool btrc_gpu_dispatch(void* gpu, void* pipeline, void* group, int count) {
    (void)gpu; (void)pipeline; (void)group; (void)count;
    if (STUB_DISPATCH_FAIL) { return false; }
    if (status_buffer != NULL && status_buffer->size >= (int)sizeof(uint32_t)) {
        uint32_t status = STUB_STATUS_CODE;
        memcpy(status_buffer->data, &status, sizeof(status));
    }
    return true;
}
