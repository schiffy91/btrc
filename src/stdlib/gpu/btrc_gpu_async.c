#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif

#include "btrc_gpu_async.h"

#include <limits.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <time.h>

#ifdef _WIN32
#include <windows.h>
#endif

struct BtrcGPUAsync {
    atomic_uint references;
    atomic_uint completion;
    int status;
    void* result;
    BtrcGPUAsyncResultRelease release_result;
};

enum {
    BTRC_GPU_ASYNC_PENDING,
    BTRC_GPU_ASYNC_COMPLETING,
    BTRC_GPU_ASYNC_DONE,
};

#ifdef BTRC_GPU_WGPU_NATIVE
static atomic_flag event_pump = ATOMIC_FLAG_INIT;
#endif

static bool monotonic_now(uint64_t* now_ns) {
#ifdef _WIN32
    uint64_t milliseconds = (uint64_t)GetTickCount64();
    if (milliseconds > UINT64_MAX / UINT64_C(1000000)) { return false; }
    *now_ns = milliseconds * UINT64_C(1000000);
    return true;
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0 || now.tv_sec < 0) {
        return false;
    }
    uint64_t seconds = (uint64_t)now.tv_sec;
    if (seconds > UINT64_MAX / UINT64_C(1000000000)) { return false; }
    *now_ns = seconds * UINT64_C(1000000000) + (uint64_t)now.tv_nsec;
    return true;
#endif
}

static void yield_to_driver(void) {
#ifdef _WIN32
    Sleep(1);
#else
    const struct timespec pause = { .tv_sec = 0, .tv_nsec = 1000000L };
    (void)nanosleep(&pause, NULL);
#endif
}

static void destroy_async(BtrcGPUAsync* async) {
    void* result = async->result;
    BtrcGPUAsyncResultRelease release_result = async->release_result;
    free(async);
    if (result && release_result) { release_result(result); }
}

BtrcGPUAsync* btrc_gpu_async_create(BtrcGPUAsyncResultRelease release_result) {
    BtrcGPUAsync* async = (BtrcGPUAsync*)calloc(1, sizeof(BtrcGPUAsync));
    if (!async) { return NULL; }
    atomic_init(&async->references, 2);
    atomic_init(&async->completion, BTRC_GPU_ASYNC_PENDING);
    async->release_result = release_result;
    return async;
}

void btrc_gpu_async_release(BtrcGPUAsync* async) {
    if (!async) { return; }
    unsigned int references = atomic_load_explicit(
        &async->references, memory_order_acquire);
    while (references != 0) {
        if (atomic_compare_exchange_weak_explicit(
                &async->references, &references, references - 1,
                memory_order_acq_rel, memory_order_acquire)) {
            if (references == 1) { destroy_async(async); }
            return;
        }
    }
}

void btrc_gpu_async_complete(BtrcGPUAsync* async, int status, void* result) {
    if (!async) { return; }
    unsigned int expected = BTRC_GPU_ASYNC_PENDING;
    if (!atomic_compare_exchange_strong_explicit(
            &async->completion, &expected, BTRC_GPU_ASYNC_COMPLETING,
            memory_order_acq_rel, memory_order_acquire)) {
        if (result && async->release_result) { async->release_result(result); }
        return;
    }
    async->status = status;
    async->result = result;
    atomic_store_explicit(
        &async->completion, BTRC_GPU_ASYNC_DONE, memory_order_release);
    btrc_gpu_async_release(async);
}

static bool completion_ready(BtrcGPUAsync* async) {
    return atomic_load_explicit(
               &async->completion, memory_order_acquire) == BTRC_GPU_ASYNC_DONE;
}

static BtrcGPUAsyncWaitOutcome poll_future(
        WGPUInstance instance, WGPUFuture future, BtrcGPUAsync* async) {
#ifdef BTRC_GPU_WGPU_NATIVE
    (void)future;
    if (!atomic_flag_test_and_set_explicit(&event_pump, memory_order_acquire)) {
        wgpuInstanceProcessEvents(instance);
        atomic_flag_clear_explicit(&event_pump, memory_order_release);
    }
    return completion_ready(async)
        ? BTRC_GPU_ASYNC_COMPLETED
        : BTRC_GPU_ASYNC_TIMED_OUT;
#else
    WGPUFutureWaitInfo wait_info = { .future = future };
    WGPUWaitStatus wait_status = wgpuInstanceWaitAny(
        instance, 1, &wait_info, 0);
    if (wait_status == WGPUWaitStatus_Success) {
        return wait_info.completed && completion_ready(async)
            ? BTRC_GPU_ASYNC_COMPLETED
            : BTRC_GPU_ASYNC_WAIT_ERROR;
    }
    return wait_status == WGPUWaitStatus_TimedOut
        ? BTRC_GPU_ASYNC_TIMED_OUT
        : BTRC_GPU_ASYNC_WAIT_ERROR;
#endif
}

BtrcGPUAsyncWaitOutcome btrc_gpu_async_wait(
        WGPUInstance instance, WGPUFuture future, BtrcGPUAsync* async,
        uint64_t timeout_ns, int* status, void** result) {
    uint64_t start = 0;
    if (!instance || !async || !monotonic_now(&start)) {
        return BTRC_GPU_ASYNC_WAIT_ERROR;
    }
    for (;;) {
        BtrcGPUAsyncWaitOutcome outcome = poll_future(
            instance, future, async);
        if (outcome == BTRC_GPU_ASYNC_COMPLETED) {
            if (status) { *status = async->status; }
            if (result) {
                *result = async->result;
                async->result = NULL;
            }
            return BTRC_GPU_ASYNC_COMPLETED;
        }
        if (outcome == BTRC_GPU_ASYNC_WAIT_ERROR) { return outcome; }
        uint64_t now = 0;
        if (!monotonic_now(&now) || now < start || now - start >= timeout_ns) {
            return BTRC_GPU_ASYNC_TIMED_OUT;
        }
        yield_to_driver();
    }
}
