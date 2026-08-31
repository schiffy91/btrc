#ifndef BTRC_GPU_ATTACH_ASYNC_TEST_REDIRECT_H
#define BTRC_GPU_ATTACH_ASYNC_TEST_REDIRECT_H

#include <stddef.h>

void* btrc_gpu_attach_async_test_calloc(size_t count, size_t size);
void btrc_gpu_attach_async_test_free(void* allocation);

#define calloc btrc_gpu_attach_async_test_calloc
#define free btrc_gpu_attach_async_test_free
#define wgpuInstanceProcessEvents btrc_gpu_attach_test_process_events

#endif
