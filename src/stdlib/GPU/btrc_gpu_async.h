#ifndef BTRC_GPU_ASYNC_H
#define BTRC_GPU_ASYNC_H

#include <stdbool.h>
#include <stdint.h>
#include <webgpu.h>

typedef void (*BtrcGPUAsyncResultRelease)(void* result);

typedef struct BtrcGPUAsync BtrcGPUAsync;

typedef enum {
    BTRC_GPU_ASYNC_COMPLETED,
    BTRC_GPU_ASYNC_TIMED_OUT,
    BTRC_GPU_ASYNC_WAIT_ERROR,
} BtrcGPUAsyncWaitOutcome;

/* wgpu-native currently exposes WaitAny but aborts when it is called. Its
 * build selects synchronized ProcessEvents pumping; conforming implementations
 * use exact-future WaitAnyOnly callbacks. */
#ifdef BTRC_GPU_WGPU_NATIVE
#define BTRC_GPU_ASYNC_CALLBACK_MODE WGPUCallbackMode_AllowProcessEvents
#else
#define BTRC_GPU_ASYNC_CALLBACK_MODE WGPUCallbackMode_WaitAnyOnly
#endif

/* Callback state owns one reference and its synchronous caller owns another.
 * This keeps userdata valid through a bounded wait and, if necessary, until
 * dropping the instance delivers CallbackCancelled. */
BtrcGPUAsync* btrc_gpu_async_create(BtrcGPUAsyncResultRelease release_result);

/* Complete one future callback. This consumes the callback's reference. */
void btrc_gpu_async_complete(BtrcGPUAsync* async, int status, void* result);

/* Conforming backends poll only this future with zero-timeout WaitAny calls.
 * The wgpu-native build serializes ProcessEvents globally and synchronizes all
 * callback state. A completed wait transfers any result handle to the caller. */
BtrcGPUAsyncWaitOutcome btrc_gpu_async_wait(
    WGPUInstance instance, WGPUFuture future, BtrcGPUAsync* async,
    uint64_t timeout_ns, int* status, void** result);

/* Release the synchronous caller's reference. An unclaimed result is released
 * through the callback supplied to btrc_gpu_async_create. */
void btrc_gpu_async_release(BtrcGPUAsync* async);

#endif
