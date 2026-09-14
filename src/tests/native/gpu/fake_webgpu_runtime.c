#define _POSIX_C_SOURCE 200809L

#include "fake_webgpu_runtime.h"

#include <assert.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

enum { MAX_FAKE_FUTURES = 16 };

typedef struct {
    BtrcGPUAsync* async;
    int status;
    void* result;
    unsigned int polls_remaining;
    bool wait_error;
    bool delivered;
    unsigned int callback_count;
    pthread_t callback_thread;
} FakeFuture;

struct WGPUInstanceImpl {
    pthread_mutex_t lock;
    FakeFuture futures[MAX_FAKE_FUTURES];
    size_t future_count;
    atomic_uint invalid_wait_count;
};

static struct WGPUInstanceImpl fake_instance = {
    .lock = PTHREAD_MUTEX_INITIALIZER,
    .invalid_wait_count = ATOMIC_VAR_INIT(0),
};
static atomic_uint process_events_active;
static atomic_uint concurrent_process_events;
static atomic_uint wait_any_call_count;

static FakeFuture* find_future(WGPUFuture future) {
    if (future.id == 0 || future.id > fake_instance.future_count) { return NULL; }
    return &fake_instance.futures[future.id - 1];
}

WGPUInstance fake_webgpu_instance(void) {
    return &fake_instance;
}

WGPUFuture fake_webgpu_make_future(
        BtrcGPUAsync* async, int status, void* result,
        unsigned int polls_remaining, bool wait_error) {
    pthread_mutex_lock(&fake_instance.lock);
    assert(fake_instance.future_count < MAX_FAKE_FUTURES);
    size_t index = fake_instance.future_count++;
    fake_instance.futures[index] = (FakeFuture){
        .async = async,
        .status = status,
        .result = result,
        .polls_remaining = polls_remaining,
        .wait_error = wait_error,
    };
    pthread_mutex_unlock(&fake_instance.lock);
    return (WGPUFuture){ .id = index + 1 };
}

void fake_webgpu_deliver(WGPUFuture future) {
    pthread_mutex_lock(&fake_instance.lock);
    FakeFuture* pending = find_future(future);
    assert(pending != NULL);
    if (pending->delivered) {
        pthread_mutex_unlock(&fake_instance.lock);
        return;
    }
    pending->delivered = true;
    pending->callback_count++;
    pending->callback_thread = pthread_self();
    BtrcGPUAsync* async = pending->async;
    int status = pending->status;
    void* result = pending->result;
    pending->async = NULL;
    pthread_mutex_unlock(&fake_instance.lock);
    btrc_gpu_async_complete(async, status, result);
}

void fake_webgpu_drop_instance(void) {
    WGPUFuture pending[MAX_FAKE_FUTURES];
    size_t pending_count = 0;
    pthread_mutex_lock(&fake_instance.lock);
    for (size_t index = 0; index < fake_instance.future_count; index++) {
        if (!fake_instance.futures[index].delivered) {
            pending[pending_count++] = (WGPUFuture){ .id = index + 1 };
        }
    }
    pthread_mutex_unlock(&fake_instance.lock);
    for (size_t index = 0; index < pending_count; index++) {
        fake_webgpu_deliver(pending[index]);
    }
}

WGPUWaitStatus wgpuInstanceWaitAny(
        WGPUInstance instance, size_t future_count,
        WGPUFutureWaitInfo* futures, uint64_t timeout_ns) {
    atomic_fetch_add_explicit(&wait_any_call_count, 1, memory_order_relaxed);
    if (instance != &fake_instance || future_count != 1 || !futures ||
        timeout_ns != 0) {
        atomic_fetch_add_explicit(
            &fake_instance.invalid_wait_count, 1, memory_order_relaxed);
        return WGPUWaitStatus_Error;
    }

    pthread_mutex_lock(&fake_instance.lock);
    FakeFuture* pending = find_future(futures[0].future);
    if (!pending || pending->wait_error) {
        pthread_mutex_unlock(&fake_instance.lock);
        return WGPUWaitStatus_Error;
    }
    if (pending->delivered) {
        futures[0].completed = 1;
        pthread_mutex_unlock(&fake_instance.lock);
        return WGPUWaitStatus_Success;
    }
    if (pending->polls_remaining > 0) {
        pending->polls_remaining--;
        pthread_mutex_unlock(&fake_instance.lock);
        return WGPUWaitStatus_TimedOut;
    }
    pthread_mutex_unlock(&fake_instance.lock);

    fake_webgpu_deliver(futures[0].future);
    futures[0].completed = 1;
    return WGPUWaitStatus_Success;
}

void wgpuInstanceProcessEvents(WGPUInstance instance) {
    if (instance != &fake_instance) {
        atomic_fetch_add_explicit(
            &fake_instance.invalid_wait_count, 1, memory_order_relaxed);
        return;
    }
    if (atomic_fetch_add_explicit(
            &process_events_active, 1, memory_order_acq_rel) != 0) {
        atomic_fetch_add_explicit(
            &concurrent_process_events, 1, memory_order_relaxed);
    }
    const struct timespec pause = { .tv_sec = 0, .tv_nsec = 1000000L };
    (void)nanosleep(&pause, NULL);

    WGPUFuture ready[MAX_FAKE_FUTURES];
    size_t ready_count = 0;
    pthread_mutex_lock(&fake_instance.lock);
    for (size_t index = 0; index < fake_instance.future_count; index++) {
        FakeFuture* pending = &fake_instance.futures[index];
        if (pending->delivered || pending->wait_error) { continue; }
        if (pending->polls_remaining > 0) {
            pending->polls_remaining--;
            continue;
        }
        ready[ready_count++] = (WGPUFuture){ .id = index + 1 };
    }
    pthread_mutex_unlock(&fake_instance.lock);
    for (size_t index = 0; index < ready_count; index++) {
        fake_webgpu_deliver(ready[index]);
    }
    atomic_fetch_sub_explicit(&process_events_active, 1, memory_order_release);
}

unsigned int fake_webgpu_callback_count(WGPUFuture future) {
    pthread_mutex_lock(&fake_instance.lock);
    FakeFuture* completed = find_future(future);
    assert(completed != NULL);
    unsigned int count = completed->callback_count;
    pthread_mutex_unlock(&fake_instance.lock);
    return count;
}

bool fake_webgpu_callback_ran_on(WGPUFuture future, pthread_t thread) {
    pthread_mutex_lock(&fake_instance.lock);
    FakeFuture* completed = find_future(future);
    assert(completed != NULL);
    bool matches = pthread_equal(completed->callback_thread, thread) != 0;
    pthread_mutex_unlock(&fake_instance.lock);
    return matches;
}

unsigned int fake_webgpu_invalid_wait_count(void) {
    return atomic_load_explicit(
        &fake_instance.invalid_wait_count, memory_order_relaxed);
}

unsigned int fake_webgpu_wait_any_call_count(void) {
    return atomic_load_explicit(&wait_any_call_count, memory_order_relaxed);
}

unsigned int fake_webgpu_concurrent_process_events(void) {
    return atomic_load_explicit(
        &concurrent_process_events, memory_order_relaxed);
}
