#ifndef FAKE_WEBGPU_RUNTIME_H
#define FAKE_WEBGPU_RUNTIME_H

#include "btrc_gpu_async.h"

#include <pthread.h>
#include <stdbool.h>

WGPUInstance fake_webgpu_instance(void);
WGPUFuture fake_webgpu_make_future(
    BtrcGPUAsync* async, int status, void* result,
    unsigned int polls_remaining, bool wait_error);
void fake_webgpu_deliver(WGPUFuture future);
void fake_webgpu_drop_instance(void);
unsigned int fake_webgpu_callback_count(WGPUFuture future);
bool fake_webgpu_callback_ran_on(WGPUFuture future, pthread_t thread);
unsigned int fake_webgpu_wait_any_call_count(void);
unsigned int fake_webgpu_invalid_wait_count(void);
unsigned int fake_webgpu_concurrent_process_events(void);

#endif
