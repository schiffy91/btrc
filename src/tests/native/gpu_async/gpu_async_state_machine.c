#include "fake_webgpu_runtime.h"

#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>

static atomic_int result_release_count;

static void release_result(void* result) {
    assert(result != NULL);
    atomic_fetch_add_explicit(&result_release_count, 1, memory_order_relaxed);
}

static int released_results(void) {
    return atomic_load_explicit(&result_release_count, memory_order_relaxed);
}

static void test_delayed_success(void) {
    int value = 1;
    int before = released_results();
    BtrcGPUAsync* async = btrc_gpu_async_create(release_result);
    assert(async != NULL);
    WGPUFuture future = fake_webgpu_make_future(async, 41, &value, 3, false);
    int status = 0;
    void* result = NULL;

    assert(btrc_gpu_async_wait(
               fake_webgpu_instance(), future, async, UINT64_C(100000000),
               &status, &result) == BTRC_GPU_ASYNC_COMPLETED);
    assert(status == 41);
    assert(result == &value);
    assert(fake_webgpu_callback_count(future) == 1);
    btrc_gpu_async_release(async);
    assert(released_results() == before);
    release_result(result);
}

static void test_timeout_then_instance_drop_cancellation(void) {
    int value = 2;
    int before = released_results();
    BtrcGPUAsync* async = btrc_gpu_async_create(release_result);
    assert(async != NULL);
    WGPUFuture future = fake_webgpu_make_future(async, 42, &value, 1, false);

    assert(btrc_gpu_async_wait(
               fake_webgpu_instance(), future, async, 0, NULL, NULL) ==
           BTRC_GPU_ASYNC_TIMED_OUT);
    btrc_gpu_async_release(async);
    assert(released_results() == before);
    fake_webgpu_drop_instance();
    fake_webgpu_drop_instance();
    assert(fake_webgpu_callback_count(future) == 1);
    assert(released_results() == before + 1);
}

static void test_unclaimed_result_released_once(void) {
    int value = 3;
    int before = released_results();
    BtrcGPUAsync* async = btrc_gpu_async_create(release_result);
    assert(async != NULL);
    WGPUFuture future = fake_webgpu_make_future(async, 43, &value, 0, false);

    assert(btrc_gpu_async_wait(
               fake_webgpu_instance(), future, async, UINT64_C(100000000),
               NULL, NULL) == BTRC_GPU_ASYNC_COMPLETED);
    btrc_gpu_async_release(async);
    assert(released_results() == before + 1);
}

#ifndef BTRC_GPU_WGPU_NATIVE
static void test_wait_error_then_late_callback(void) {
    int value = 4;
    int before = released_results();
    BtrcGPUAsync* async = btrc_gpu_async_create(release_result);
    assert(async != NULL);
    WGPUFuture future = fake_webgpu_make_future(async, 44, &value, 0, true);

    assert(btrc_gpu_async_wait(
               fake_webgpu_instance(), future, async, UINT64_C(100000000),
               NULL, NULL) == BTRC_GPU_ASYNC_WAIT_ERROR);
    btrc_gpu_async_release(async);
    fake_webgpu_deliver(future);
    assert(released_results() == before + 1);
}
#endif

typedef struct {
    BtrcGPUAsync* async;
    WGPUFuture future;
    int expected_status;
    void* expected_result;
    void* result;
} WaitThread;

static void* wait_for_distinct_future(void* userdata) {
    WaitThread* thread = (WaitThread*)userdata;
    int status = 0;
    assert(btrc_gpu_async_wait(
               fake_webgpu_instance(), thread->future, thread->async,
               UINT64_C(100000000), &status, &thread->result) ==
           BTRC_GPU_ASYNC_COMPLETED);
    assert(status == thread->expected_status);
    assert(thread->result == thread->expected_result);
#ifndef BTRC_GPU_WGPU_NATIVE
    assert(fake_webgpu_callback_ran_on(thread->future, pthread_self()));
#endif
    return NULL;
}

static void test_concurrent_distinct_futures(void) {
    int first_value = 5;
    int second_value = 6;
    WaitThread first = {
        .async = btrc_gpu_async_create(release_result),
        .expected_status = 45,
        .expected_result = &first_value,
    };
    WaitThread second = {
        .async = btrc_gpu_async_create(release_result),
        .expected_status = 46,
        .expected_result = &second_value,
    };
    assert(first.async != NULL && second.async != NULL);
    first.future = fake_webgpu_make_future(
        first.async, 45, &first_value, 4, false);
    second.future = fake_webgpu_make_future(
        second.async, 46, &second_value, 2, false);

    pthread_t first_thread;
    pthread_t second_thread;
    assert(pthread_create(
               &first_thread, NULL, wait_for_distinct_future, &first) == 0);
    assert(pthread_create(
               &second_thread, NULL, wait_for_distinct_future, &second) == 0);
    assert(pthread_join(first_thread, NULL) == 0);
    assert(pthread_join(second_thread, NULL) == 0);
    assert(fake_webgpu_callback_count(first.future) == 1);
    assert(fake_webgpu_callback_count(second.future) == 1);
    btrc_gpu_async_release(first.async);
    btrc_gpu_async_release(second.async);
    release_result(first.result);
    release_result(second.result);
}

int main(void) {
    test_delayed_success();
    test_timeout_then_instance_drop_cancellation();
    test_unclaimed_result_released_once();
#ifndef BTRC_GPU_WGPU_NATIVE
    test_wait_error_then_late_callback();
#endif
    test_concurrent_distinct_futures();
    assert(fake_webgpu_invalid_wait_count() == 0);
    assert(fake_webgpu_concurrent_process_events() == 0);
#ifdef BTRC_GPU_WGPU_NATIVE
    assert(fake_webgpu_wait_any_call_count() == 0);
#else
    assert(fake_webgpu_wait_any_call_count() > 0);
#endif
    return 0;
}
