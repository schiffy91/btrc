#include "btrc_app_surface_internal.h"
#include "btrc_gpu.h"

#include <GLFW/glfw3.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <webgpu.h>

enum {
    TEST_SURFACE_ID = 42,
    TEST_FRAMEBUFFER_WIDTH = 800,
    TEST_FRAMEBUFFER_HEIGHT = 600,
};

typedef enum {
    TEST_READY,
    TEST_APP_INVALID,
    TEST_APP_BUSY,
    TEST_APP_NOT_OWNER,
    TEST_APP_INTERNAL,
    TEST_WINDOW_INVALID,
    TEST_GPU_ALLOCATION,
    TEST_MUTEX_INITIALIZATION,
    TEST_INSTANCE_CREATION,
    TEST_SURFACE_CREATION,
    TEST_ADAPTER_ASYNC_ALLOCATION,
    TEST_ADAPTER_REQUEST,
    TEST_DEVICE_ASYNC_ALLOCATION,
    TEST_DEVICE_LOST_ASYNC_ALLOCATION,
    TEST_DEVICE_REQUEST,
    TEST_QUEUE_ACQUISITION,
    TEST_CAPABILITY_STATUS,
    TEST_CAPABILITY_FORMATS,
    TEST_CAPABILITY_ALPHA_MODES,
    TEST_FRAMEBUFFER_SIZE,
} TestStage;

typedef enum {
    EVENT_CAPABILITIES_FREED,
    EVENT_SURFACE_UNCONFIGURED,
    EVENT_QUEUE_RELEASED,
    EVENT_DEVICE_DESTROYED,
    EVENT_DEVICE_RELEASED,
    EVENT_ADAPTER_RELEASED,
    EVENT_SURFACE_RELEASED,
    EVENT_INSTANCE_RELEASED,
    EVENT_MUTEX_DESTROYED,
    EVENT_LEASE_DETACHED,
    EVENT_GPU_FREED,
} TestEvent;

typedef struct {
    TestStage stage;
    TestEvent events[32];
    size_t event_count;
    size_t attach_count;
    size_t detach_count;
    size_t allocation_attempts;
    size_t gpu_allocations;
    size_t gpu_frees;
    size_t async_allocation_attempts;
    size_t async_allocations;
    size_t async_frees;
    size_t mutex_initializations;
    size_t mutex_destructions;
    size_t process_events;
    size_t capability_frees;
    size_t surface_configurations;
    size_t surface_unconfigurations;
    bool lease_attached;
    bool device_lost_pending;
    WGPUDeviceLostCallbackInfo device_lost;
    unsigned long long next_future;
    pthread_t owner_thread;
} TestState;

struct BtrcAppSurfaceLease {
    unsigned long long surface_id;
};

static TestState state;
static BtrcAppOwnerDrainHook registered_owner_drain;
static struct BtrcAppSurfaceLease lease = { TEST_SURFACE_ID };
static unsigned char window_token;
static unsigned char instance_token;
static unsigned char surface_token;
static unsigned char adapter_token;
static unsigned char device_token;
static unsigned char queue_token;

#define ARRAY_COUNT(values) (sizeof(values) / sizeof((values)[0]))

static void require(bool condition, const char* message) {
    if (condition) { return; }
    fprintf(stderr, "gpu attach runtime test failed: %s\n", message);
    abort();
}

static void record_event(TestEvent event) {
    require(state.event_count < ARRAY_COUNT(state.events), "event log overflow");
    state.events[state.event_count++] = event;
}

static void reset_state(TestStage stage) {
    require(!state.lease_attached, "previous lease was not detached");
    require(state.gpu_allocations == state.gpu_frees,
            "previous GPU allocation was not freed");
    require(state.async_allocations == state.async_frees,
            "previous async allocation was not freed");
    require(!state.device_lost_pending,
            "previous device-lost callback was not completed");
    memset(&state, 0, sizeof(state));
    state.stage = stage;
    state.next_future = 1;
    state.owner_thread = pthread_self();
}

static void expect_events(const TestEvent* expected, size_t count) {
    require(state.event_count == count, "unexpected cleanup event count");
    for (size_t index = 0; index < count; index += 1) {
        require(state.events[index] == expected[index],
                "cleanup event order mismatch");
    }
}

static WGPUFuture next_future(void) {
    WGPUFuture future = { .id = state.next_future };
    state.next_future += 1;
    return future;
}

static WGPUStringView empty_message(void) {
    return (WGPUStringView){ .data = "", .length = 0 };
}

static WGPUInstance test_instance(void) {
    return (WGPUInstance)(void*)&instance_token;
}

static WGPUSurface test_surface(void) {
    return (WGPUSurface)(void*)&surface_token;
}

static WGPUAdapter test_adapter(void) {
    return (WGPUAdapter)(void*)&adapter_token;
}

static WGPUDevice test_device(void) {
    return (WGPUDevice)(void*)&device_token;
}

static WGPUQueue test_queue(void) {
    return (WGPUQueue)(void*)&queue_token;
}

void btrc_app_register_owner_drain_hook(BtrcAppOwnerDrainHook hook) {
    require(hook != NULL, "registered null application owner-drain hook");
    if (registered_owner_drain) {
        require(registered_owner_drain == hook,
                "application owner-drain hook changed");
    }
    registered_owner_drain = hook;
}

void btrc_app_drain_owner_finalizers(void) {
    if (registered_owner_drain) { registered_owner_drain(); }
}

int std_app_surface_attach(
        unsigned long long surface_id, BtrcAppSurfaceLease** lease_out) {
    require(lease_out != NULL, "application lease output is null");
    *lease_out = NULL;
    state.attach_count += 1;
    if (state.stage == TEST_APP_INVALID || surface_id != TEST_SURFACE_ID) {
        return BTRC_APP_ERROR_STALE_SURFACE;
    }
    if (state.stage == TEST_APP_BUSY || state.lease_attached) {
        return BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED;
    }
    if (state.stage == TEST_APP_NOT_OWNER) {
        return BTRC_APP_ERROR_NOT_MAIN_THREAD;
    }
    if (state.stage == TEST_APP_INTERNAL) { return BTRC_APP_ERROR_INTERNAL; }
    state.lease_attached = true;
    *lease_out = &lease;
    return BTRC_APP_ERROR_NONE;
}

GLFWwindow* std_app_surface_glfw(BtrcAppSurfaceLease* attached_lease) {
    require(attached_lease == &lease, "unexpected application lease");
    if (pthread_equal(state.owner_thread, pthread_self()) == 0) { return NULL; }
    if (state.stage == TEST_WINDOW_INVALID) { return NULL; }
    return (GLFWwindow*)(void*)&window_token;
}

unsigned long long std_app_surface_lease_generation(
        BtrcAppSurfaceLease* attached_lease) {
    require(attached_lease == &lease, "unexpected generation lease");
    return 1;
}

int std_app_surface_detach(BtrcAppSurfaceLease* attached_lease) {
    require(attached_lease == &lease, "unexpected detached lease");
    require(state.lease_attached, "application lease detached twice");
    state.lease_attached = false;
    state.detach_count += 1;
    record_event(EVENT_LEASE_DETACHED);
    return BTRC_APP_ERROR_NONE;
}

void* btrc_gpu_attach_test_calloc(size_t count, size_t size) {
    state.allocation_attempts += 1;
    if (state.stage == TEST_GPU_ALLOCATION) { return NULL; }
    void* allocation = calloc(count, size);
    if (allocation) { state.gpu_allocations += 1; }
    return allocation;
}

void btrc_gpu_attach_test_free(void* allocation) {
    require(allocation != NULL, "GPU free received null");
    require(state.gpu_allocations > state.gpu_frees, "GPU allocation freed twice");
    state.gpu_frees += 1;
    record_event(EVENT_GPU_FREED);
    free(allocation);
}

void* btrc_gpu_attach_async_test_calloc(size_t count, size_t size) {
    state.async_allocation_attempts += 1;
    size_t attempt = state.async_allocation_attempts;
    if ((state.stage == TEST_ADAPTER_ASYNC_ALLOCATION && attempt == 1) ||
        (state.stage == TEST_DEVICE_ASYNC_ALLOCATION && attempt == 2) ||
        (state.stage == TEST_DEVICE_LOST_ASYNC_ALLOCATION && attempt == 3)) {
        return NULL;
    }
    void* allocation = calloc(count, size);
    if (allocation) { state.async_allocations += 1; }
    return allocation;
}

void btrc_gpu_attach_async_test_free(void* allocation) {
    require(allocation != NULL, "async free received null");
    require(state.async_allocations > state.async_frees,
            "async allocation freed twice");
    state.async_frees += 1;
    free(allocation);
}

int btrc_gpu_attach_test_mutex_init(
        pthread_mutex_t* mutex, const pthread_mutexattr_t* attributes) {
    state.mutex_initializations += 1;
    if (state.stage == TEST_MUTEX_INITIALIZATION) { return EAGAIN; }
    return pthread_mutex_init(mutex, attributes);
}

int btrc_gpu_attach_test_mutex_destroy(pthread_mutex_t* mutex) {
    state.mutex_destructions += 1;
    record_event(EVENT_MUTEX_DESTROYED);
    return pthread_mutex_destroy(mutex);
}

WGPUInstance btrc_gpu_attach_test_create_instance(
        const WGPUInstanceDescriptor* descriptor) {
    require(descriptor == NULL, "unexpected instance descriptor");
    return state.stage == TEST_INSTANCE_CREATION ? NULL : test_instance();
}

WGPUSurface btrc_gpu_attach_test_create_surface(
        WGPUInstance instance, GLFWwindow* window) {
    require(instance == test_instance(), "surface received wrong instance");
    require(window == (GLFWwindow*)(void*)&window_token,
            "surface received wrong window");
    return state.stage == TEST_SURFACE_CREATION ? NULL : test_surface();
}

WGPUFuture btrc_gpu_attach_test_request_adapter(
        WGPUInstance instance,
        const WGPURequestAdapterOptions* options,
        WGPURequestAdapterCallbackInfo callback_info) {
    require(instance == test_instance(), "adapter request received wrong instance");
    require(options != NULL && options->compatibleSurface == test_surface(),
            "adapter request received wrong surface");
    require(callback_info.callback != NULL, "adapter request callback is null");
    if (state.stage == TEST_ADAPTER_REQUEST) {
        callback_info.callback(
            WGPURequestAdapterStatus_Error,
            NULL,
            empty_message(),
            callback_info.userdata1,
            callback_info.userdata2);
    } else {
        callback_info.callback(
            WGPURequestAdapterStatus_Success,
            test_adapter(),
            empty_message(),
            callback_info.userdata1,
            callback_info.userdata2);
    }
    return next_future();
}

static void complete_device_lost(
        WGPUDevice device, WGPUDeviceLostReason reason) {
    require(state.device_lost_pending, "device-lost callback completed twice");
    require(state.device_lost.callback != NULL, "device-lost callback is null");
    state.device_lost.callback(
        &device,
        reason,
        empty_message(),
        state.device_lost.userdata1,
        state.device_lost.userdata2);
    state.device_lost_pending = false;
}

WGPUFuture btrc_gpu_attach_test_request_device(
        WGPUAdapter adapter,
        const WGPUDeviceDescriptor* descriptor,
        WGPURequestDeviceCallbackInfo callback_info) {
    require(adapter == test_adapter(), "device request received wrong adapter");
    require(descriptor != NULL, "device descriptor is null");
    require(callback_info.callback != NULL, "device request callback is null");
    state.device_lost = descriptor->deviceLostCallbackInfo;
    state.device_lost_pending = true;
    if (state.stage == TEST_DEVICE_REQUEST) {
        callback_info.callback(
            WGPURequestDeviceStatus_Error,
            NULL,
            empty_message(),
            callback_info.userdata1,
            callback_info.userdata2);
        complete_device_lost(NULL, WGPUDeviceLostReason_FailedCreation);
    } else {
        callback_info.callback(
            WGPURequestDeviceStatus_Success,
            test_device(),
            empty_message(),
            callback_info.userdata1,
            callback_info.userdata2);
    }
    return next_future();
}

WGPUQueue btrc_gpu_attach_test_get_queue(WGPUDevice device) {
    require(device == test_device(), "queue request received wrong device");
    return state.stage == TEST_QUEUE_ACQUISITION ? NULL : test_queue();
}

WGPUStatus btrc_gpu_attach_test_get_capabilities(
        WGPUSurface surface,
        WGPUAdapter adapter,
        WGPUSurfaceCapabilities* capabilities) {
    static const WGPUTextureFormat formats[] = {
        WGPUTextureFormat_BGRA8Unorm,
    };
    static const WGPUCompositeAlphaMode alpha_modes[] = {
        WGPUCompositeAlphaMode_Opaque,
    };
    require(surface == test_surface(), "capabilities received wrong surface");
    require(adapter == test_adapter(), "capabilities received wrong adapter");
    require(capabilities != NULL, "capabilities output is null");
    if (state.stage == TEST_CAPABILITY_STATUS) { return WGPUStatus_Error; }
    if (state.stage != TEST_CAPABILITY_FORMATS) {
        capabilities->formatCount = ARRAY_COUNT(formats);
        capabilities->formats = formats;
    }
    if (state.stage != TEST_CAPABILITY_ALPHA_MODES) {
        capabilities->alphaModeCount = ARRAY_COUNT(alpha_modes);
        capabilities->alphaModes = alpha_modes;
    }
    return WGPUStatus_Success;
}

void btrc_gpu_attach_test_free_capabilities(
        WGPUSurfaceCapabilities capabilities) {
    (void)capabilities;
    state.capability_frees += 1;
    record_event(EVENT_CAPABILITIES_FREED);
}

void btrc_gpu_attach_test_get_framebuffer_size(
        GLFWwindow* window, int* width, int* height) {
    require(window == (GLFWwindow*)(void*)&window_token,
            "framebuffer query received wrong window");
    require(width != NULL && height != NULL, "framebuffer output is null");
    if (state.stage == TEST_FRAMEBUFFER_SIZE) {
        *width = 0;
        *height = 0;
    } else {
        *width = TEST_FRAMEBUFFER_WIDTH;
        *height = TEST_FRAMEBUFFER_HEIGHT;
    }
}

void btrc_gpu_attach_test_configure_surface(
        WGPUSurface surface, const WGPUSurfaceConfiguration* configuration) {
    require(surface == test_surface(), "configuration received wrong surface");
    require(configuration != NULL, "surface configuration is null");
    require(configuration->device == test_device(),
            "configuration received wrong device");
    require(configuration->format == WGPUTextureFormat_BGRA8Unorm,
            "configuration received wrong format");
    require(configuration->alphaMode == WGPUCompositeAlphaMode_Opaque,
            "configuration received wrong alpha mode");
    require(configuration->width == TEST_FRAMEBUFFER_WIDTH &&
                configuration->height == TEST_FRAMEBUFFER_HEIGHT,
            "configuration received wrong framebuffer size");
    state.surface_configurations += 1;
}

void btrc_gpu_attach_test_unconfigure_surface(WGPUSurface surface) {
    require(surface == test_surface(), "unconfigured wrong surface");
    require(state.surface_configurations == 1,
            "surface was unconfigured before configuration");
    require(state.surface_unconfigurations == 0,
            "surface was unconfigured twice");
    state.surface_unconfigurations += 1;
    record_event(EVENT_SURFACE_UNCONFIGURED);
}

void btrc_gpu_attach_test_process_events(WGPUInstance instance) {
    require(instance == test_instance(), "event pump received wrong instance");
    state.process_events += 1;
}

void btrc_gpu_attach_test_release_queue(WGPUQueue queue) {
    require(queue == test_queue(), "released wrong queue");
    record_event(EVENT_QUEUE_RELEASED);
}

void btrc_gpu_attach_test_destroy_device(WGPUDevice device) {
    require(device == test_device(), "destroyed wrong device");
    record_event(EVENT_DEVICE_DESTROYED);
    complete_device_lost(device, WGPUDeviceLostReason_Destroyed);
}

void btrc_gpu_attach_test_release_device(WGPUDevice device) {
    require(device == test_device(), "released wrong device");
    record_event(EVENT_DEVICE_RELEASED);
}

void btrc_gpu_attach_test_release_adapter(WGPUAdapter adapter) {
    require(adapter == test_adapter(), "released wrong adapter");
    record_event(EVENT_ADAPTER_RELEASED);
}

void btrc_gpu_attach_test_release_surface(WGPUSurface surface) {
    require(surface == test_surface(), "released wrong surface");
    record_event(EVENT_SURFACE_RELEASED);
}

void btrc_gpu_attach_test_release_instance(WGPUInstance instance) {
    require(instance == test_instance(), "released wrong instance");
    record_event(EVENT_INSTANCE_RELEASED);
}

static void expect_attach_failure(
        TestStage stage,
        int expected_status,
        const TestEvent* expected_events,
        size_t expected_event_count) {
    reset_state(stage);
    unsigned long long gpu = UINT64_MAX;
    unsigned long long owner_receipt = UINT64_MAX;
    int status = std_gpu_attach_surface(
        TEST_SURFACE_ID, &gpu, &owner_receipt);
    require(status == expected_status, "unexpected typed attach failure");
    require(gpu == 0, "failed attach published a GPU owner");
    require(owner_receipt == 0,
            "failed attach published a GPU owner receipt");
    require(!state.lease_attached, "failed attach retained the application lease");
    require(state.gpu_allocations == state.gpu_frees,
            "failed attach leaked its GPU allocation");
    require(state.async_allocations == state.async_frees,
            "failed attach leaked async callback state");
    require(!state.device_lost_pending,
            "failed attach retained a device-lost callback");
    expect_events(expected_events, expected_event_count);
}

static void test_early_rejections(void) {
    reset_state(TEST_READY);
    unsigned long long gpu = UINT64_MAX;
    unsigned long long owner_receipt = UINT64_MAX;
    require(std_gpu_attach_surface(
                TEST_SURFACE_ID, NULL, &owner_receipt) ==
                BTRC_GPU_ATTACH_INVALID_SURFACE,
            "null GPU output was not rejected");
    require(owner_receipt == UINT64_MAX,
            "rejected null GPU output modified the receipt output");
    require(std_gpu_attach_surface(TEST_SURFACE_ID, &gpu, NULL) ==
                BTRC_GPU_ATTACH_INVALID_SURFACE,
            "null receipt output was not rejected");
    require(gpu == UINT64_MAX,
            "rejected null receipt output modified the GPU output");
    require(state.attach_count == 0, "null output acquired an application lease");

    unsigned long long resource = UINT64_MAX;
    unsigned long long resource_receipt = UINT64_MAX;
    require(std_gpu_shader_create(
                0, "invalid GPU", &resource, &resource_receipt) ==
                BTRC_GPU_RESOURCE_INVALID_GPU,
            "invalid GPU shader creation was not typed");
    require(resource == 0 && resource_receipt == 0,
            "failed shader creation did not zero both outputs");
    resource = UINT64_MAX;
    resource_receipt = UINT64_MAX;
    require(std_gpu_pipeline_create(
                0, 0, "vs_main", "fs_main",
                &resource, &resource_receipt) ==
                BTRC_GPU_RESOURCE_INVALID_GPU,
            "invalid GPU pipeline creation was not typed");
    require(resource == 0 && resource_receipt == 0,
            "failed pipeline creation did not zero both outputs");
    resource = UINT64_MAX;
    resource_receipt = UINT64_MAX;
    require(std_gpu_uniform_create(
                0, 1, &resource, &resource_receipt) ==
                BTRC_GPU_RESOURCE_INVALID_GPU,
            "invalid GPU uniform creation was not typed");
    require(resource == 0 && resource_receipt == 0,
            "failed uniform creation did not zero both outputs");

    expect_attach_failure(
        TEST_APP_INVALID, BTRC_GPU_ATTACH_INVALID_SURFACE, NULL, 0);
    expect_attach_failure(
        TEST_APP_BUSY, BTRC_GPU_ATTACH_SURFACE_BUSY, NULL, 0);
    expect_attach_failure(
        TEST_APP_NOT_OWNER, BTRC_GPU_ATTACH_NOT_OWNER_THREAD, NULL, 0);
    expect_attach_failure(
        TEST_APP_INTERNAL, BTRC_GPU_ATTACH_INTERNAL_ERROR, NULL, 0);

    const TestEvent window_events[] = { EVENT_LEASE_DETACHED };
    expect_attach_failure(
        TEST_WINDOW_INVALID,
        BTRC_GPU_ATTACH_INVALID_SURFACE,
        window_events,
        ARRAY_COUNT(window_events));

    const TestEvent allocation_events[] = { EVENT_LEASE_DETACHED };
    expect_attach_failure(
        TEST_GPU_ALLOCATION,
        BTRC_GPU_ATTACH_OUT_OF_MEMORY,
        allocation_events,
        ARRAY_COUNT(allocation_events));
    require(state.allocation_attempts == 1, "GPU allocation was not attempted once");

    const TestEvent mutex_events[] = {
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(
        TEST_MUTEX_INITIALIZATION,
        BTRC_GPU_ATTACH_INTERNAL_ERROR,
        mutex_events,
        ARRAY_COUNT(mutex_events));
    require(state.mutex_destructions == 0,
            "failed mutex initialization was destroyed");
}

static void test_native_partial_initialization(void) {
    const TestEvent instance_events[] = {
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(
        TEST_INSTANCE_CREATION,
        BTRC_GPU_ATTACH_INTERNAL_ERROR,
        instance_events,
        ARRAY_COUNT(instance_events));

    const TestEvent surface_events[] = {
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(
        TEST_SURFACE_CREATION,
        BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED,
        surface_events,
        ARRAY_COUNT(surface_events));

    const TestEvent adapter_events[] = {
        EVENT_SURFACE_RELEASED,
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(
        TEST_ADAPTER_ASYNC_ALLOCATION,
        BTRC_GPU_ATTACH_ADAPTER_UNAVAILABLE,
        adapter_events,
        ARRAY_COUNT(adapter_events));
    expect_attach_failure(
        TEST_ADAPTER_REQUEST,
        BTRC_GPU_ATTACH_ADAPTER_UNAVAILABLE,
        adapter_events,
        ARRAY_COUNT(adapter_events));

    const TestEvent device_events[] = {
        EVENT_ADAPTER_RELEASED,
        EVENT_SURFACE_RELEASED,
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(
        TEST_DEVICE_ASYNC_ALLOCATION,
        BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE,
        device_events,
        ARRAY_COUNT(device_events));
    expect_attach_failure(
        TEST_DEVICE_LOST_ASYNC_ALLOCATION,
        BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE,
        device_events,
        ARRAY_COUNT(device_events));
    expect_attach_failure(
        TEST_DEVICE_REQUEST,
        BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE,
        device_events,
        ARRAY_COUNT(device_events));

    const TestEvent queue_events[] = {
        EVENT_DEVICE_DESTROYED,
        EVENT_DEVICE_RELEASED,
        EVENT_ADAPTER_RELEASED,
        EVENT_SURFACE_RELEASED,
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(
        TEST_QUEUE_ACQUISITION,
        BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE,
        queue_events,
        ARRAY_COUNT(queue_events));
}

static void expect_capability_failure(TestStage stage, int expected_status) {
    const TestEvent events[] = {
        EVENT_CAPABILITIES_FREED,
        EVENT_QUEUE_RELEASED,
        EVENT_DEVICE_DESTROYED,
        EVENT_DEVICE_RELEASED,
        EVENT_ADAPTER_RELEASED,
        EVENT_SURFACE_RELEASED,
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    expect_attach_failure(stage, expected_status, events, ARRAY_COUNT(events));
    require(state.capability_frees == 1,
            "surface capabilities were not freed exactly once");
}

static void test_surface_configuration_failures(void) {
    expect_capability_failure(
        TEST_CAPABILITY_STATUS, BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED);
    expect_capability_failure(
        TEST_CAPABILITY_FORMATS, BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED);
    expect_capability_failure(
        TEST_CAPABILITY_ALPHA_MODES, BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED);
    expect_capability_failure(
        TEST_FRAMEBUFFER_SIZE, BTRC_GPU_ATTACH_INVALID_SURFACE);
}

typedef struct {
    unsigned long long gpu;
    unsigned long long owner_receipt;
    int begin_status;
    int end_status;
    unsigned long long shader;
    unsigned long long uniform;
    int shader_status;
    int uniform_status;
    int destroy_shader_status;
    int set_uniform_status;
    int status;
} WorkerClose;

static void* close_gpu_on_worker(void* context) {
    WorkerClose* close = (WorkerClose*)context;
    unsigned long long shader_receipt = UINT64_MAX;
    unsigned long long uniform_receipt = UINT64_MAX;
    close->begin_status = std_gpu_begin_frame(close->gpu, 0, 0, 0, 1);
    close->end_status = std_gpu_end_frame(close->gpu);
    close->shader_status = std_gpu_shader_create(
        close->gpu, "owner-only", &close->shader, &shader_receipt);
    close->uniform_status = std_gpu_uniform_create(
        close->gpu, 1, &close->uniform, &uniform_receipt);
    close->destroy_shader_status = std_gpu_shader_destroy(
        UINT64_MAX, UINT64_MAX);
    close->set_uniform_status = std_gpu_uniform_set(UINT64_MAX, 0, 1.0f);
    close->status = std_gpu_close(close->gpu, close->owner_receipt);
    require(shader_receipt == 0 && uniform_receipt == 0,
            "wrong-thread resource creation published an owner receipt");
    return NULL;
}

typedef struct {
    unsigned long long gpu;
    unsigned long long owner_receipt;
    int explicit_close_status;
} WorkerFinalize;

static void* finalize_gpu_on_worker(void* context) {
    WorkerFinalize* finalize = (WorkerFinalize*)context;
    finalize->explicit_close_status = std_gpu_close(
        finalize->gpu, finalize->owner_receipt);
    std_gpu_finalize(finalize->gpu, finalize->owner_receipt);
    return NULL;
}

static void test_ready_lifetime(void) {
    const TestEvent events[] = {
        EVENT_CAPABILITIES_FREED,
        EVENT_SURFACE_UNCONFIGURED,
        EVENT_QUEUE_RELEASED,
        EVENT_DEVICE_DESTROYED,
        EVENT_DEVICE_RELEASED,
        EVENT_ADAPTER_RELEASED,
        EVENT_SURFACE_RELEASED,
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    unsigned long long stale_gpu = 0;
    unsigned long long stale_owner_receipt = 0;
    for (size_t iteration = 0; iteration < 32; iteration += 1) {
        reset_state(TEST_READY);
        unsigned long long gpu = 0;
        unsigned long long owner_receipt = 0;
        require(std_gpu_attach_surface(
                    TEST_SURFACE_ID, &gpu, &owner_receipt) ==
                    BTRC_GPU_ATTACH_READY,
                "valid surface did not attach");
        require(gpu != 0, "ready attach did not publish its GPU owner");
        require(owner_receipt != 0,
                "ready attach did not publish its GPU owner receipt");
        if (stale_gpu != 0) {
            require(gpu != stale_gpu,
                    "reattach reused a stale GPU capability");
            require(std_gpu_close(stale_gpu, stale_owner_receipt) ==
                        BTRC_GPU_CLOSE_INVALID,
                    "stale GPU capability closed the new owner");
            require(state.lease_attached,
                    "stale GPU close detached the new application lease");
        }
        require(state.lease_attached, "ready attach did not retain its lease");
        require(state.capability_frees == 1,
                "ready attach did not free capabilities exactly once");
        require(state.surface_configurations == 1,
                "ready attach did not configure the surface exactly once");
        require(state.surface_unconfigurations == 0,
                "ready attach unconfigured its live surface");

        unsigned long long duplicate = UINT64_MAX;
        unsigned long long duplicate_receipt = UINT64_MAX;
        require(std_gpu_attach_surface(
                    TEST_SURFACE_ID, &duplicate, &duplicate_receipt) ==
                    BTRC_GPU_ATTACH_SURFACE_BUSY,
                "duplicate GPU ownership was not rejected");
        require(duplicate == 0, "duplicate attach published a GPU owner");
        require(duplicate_receipt == 0,
                "duplicate attach published a GPU owner receipt");

        if (iteration == 0) {
            WorkerClose worker_close = {
                .gpu = gpu,
                .owner_receipt = owner_receipt,
                .begin_status = BTRC_GPU_FRAME_READY,
                .end_status = BTRC_GPU_FRAME_PRESENTED,
                .shader = UINT64_MAX,
                .uniform = UINT64_MAX,
                .shader_status = BTRC_GPU_RESOURCE_READY,
                .uniform_status = BTRC_GPU_RESOURCE_READY,
                .destroy_shader_status = BTRC_GPU_CLOSE_CLOSED,
                .set_uniform_status = 1,
                .status = BTRC_GPU_CLOSE_INVALID,
            };
            pthread_t worker;
            require(pthread_create(
                        &worker, NULL, close_gpu_on_worker, &worker_close) == 0,
                    "failed to create wrong-thread close worker");
            require(pthread_join(worker, NULL) == 0,
                    "failed to join wrong-thread close worker");
            require(worker_close.status == BTRC_GPU_CLOSE_NOT_OWNER_THREAD,
                    "wrong-thread GPU close was not rejected");
            require(worker_close.begin_status == BTRC_GPU_FRAME_REJECTED &&
                        worker_close.end_status == BTRC_GPU_FRAME_REJECTED,
                    "wrong-thread frame operation was not rejected");
            require(worker_close.shader == 0 && worker_close.uniform == 0 &&
                        worker_close.shader_status ==
                            BTRC_GPU_RESOURCE_NOT_OWNER_THREAD &&
                        worker_close.uniform_status ==
                            BTRC_GPU_RESOURCE_NOT_OWNER_THREAD &&
                        worker_close.destroy_shader_status ==
                            BTRC_GPU_CLOSE_INVALID &&
                        worker_close.set_uniform_status ==
                            BTRC_GPU_RESOURCE_INVALID_RESOURCE,
                    "wrong-thread resource operation was not rejected");
            require(state.lease_attached,
                    "wrong-thread GPU close detached the application lease");
            require(state.gpu_allocations > state.gpu_frees,
                    "wrong-thread GPU close destroyed the GPU owner");
        }

        unsigned long long wrong_receipt = owner_receipt + 1;
        require(wrong_receipt != 0 && wrong_receipt != owner_receipt,
                "failed to choose a distinct wrong owner receipt");
        require(std_gpu_close(gpu, wrong_receipt) == BTRC_GPU_CLOSE_INVALID,
                "wrong GPU owner receipt closed the canonical owner");
        std_gpu_finalize(gpu, wrong_receipt);
        require(state.lease_attached,
                "wrong GPU owner receipt finalized the canonical owner");

        require(std_gpu_close(gpu, owner_receipt) == BTRC_GPU_CLOSE_CLOSED,
                "owner-thread GPU close was rejected");
        require(!state.lease_attached, "GPU close retained its application lease");
        require(state.gpu_allocations == state.gpu_frees,
                "GPU close leaked its owner allocation");
        require(state.async_allocations == state.async_frees,
                "GPU close leaked async callback state");
        require(!state.device_lost_pending,
                "GPU close retained its device-lost callback");
        require(state.surface_unconfigurations == 1,
                "GPU close did not unconfigure its surface exactly once");
        require(state.mutex_initializations == 1 &&
                    state.mutex_destructions == 1,
                "GPU close did not balance pending-list lifetime");
        expect_events(events, ARRAY_COUNT(events));
        stale_gpu = gpu;
        stale_owner_receipt = owner_receipt;
    }
    require(std_gpu_close(0, 0) == BTRC_GPU_CLOSE_INVALID,
            "null GPU close was not rejected");
}

static void test_worker_last_reference_finalization(void) {
    const TestEvent events[] = {
        EVENT_CAPABILITIES_FREED,
        EVENT_SURFACE_UNCONFIGURED,
        EVENT_QUEUE_RELEASED,
        EVENT_DEVICE_DESTROYED,
        EVENT_DEVICE_RELEASED,
        EVENT_ADAPTER_RELEASED,
        EVENT_SURFACE_RELEASED,
        EVENT_INSTANCE_RELEASED,
        EVENT_MUTEX_DESTROYED,
        EVENT_LEASE_DETACHED,
        EVENT_GPU_FREED,
    };
    reset_state(TEST_READY);
    unsigned long long gpu = 0;
    unsigned long long owner_receipt = 0;
    require(std_gpu_attach_surface(
                TEST_SURFACE_ID, &gpu, &owner_receipt) ==
                BTRC_GPU_ATTACH_READY,
            "worker-finalizer surface did not attach");
    require(registered_owner_drain != NULL,
            "GPU attachment did not register an owner-drain hook");

    WorkerFinalize finalize = {
        .gpu = gpu,
        .owner_receipt = owner_receipt,
        .explicit_close_status = BTRC_GPU_CLOSE_INVALID,
    };
    pthread_t worker;
    require(pthread_create(
                &worker, NULL, finalize_gpu_on_worker, &finalize) == 0,
            "failed to create GPU finalizer worker");
    require(pthread_join(worker, NULL) == 0,
            "failed to join GPU finalizer worker");
    require(finalize.explicit_close_status ==
                BTRC_GPU_CLOSE_NOT_OWNER_THREAD,
            "worker explicit close did not preserve typed rejection");
    require(state.lease_attached,
            "worker finalizer synchronously detached the application lease");
    require(state.gpu_allocations > state.gpu_frees,
            "worker finalizer synchronously freed the GPU");

    registered_owner_drain();
    require(!state.lease_attached,
            "owner drain retained the finalized application lease");
    require(state.gpu_allocations == state.gpu_frees,
            "owner drain leaked the finalized GPU");
    require(state.surface_unconfigurations == 1,
            "owner drain did not unconfigure exactly once");
    expect_events(events, ARRAY_COUNT(events));

    size_t event_count = state.event_count;
    std_gpu_finalize(gpu, owner_receipt);
    registered_owner_drain();
    require(state.event_count == event_count,
            "stale GPU finalizer affected an already-closed owner");
    require(std_gpu_close(gpu, owner_receipt) == BTRC_GPU_CLOSE_INVALID,
            "finalized GPU capability remained live");
}

int main(void) {
    test_early_rejections();
    test_native_partial_initialization();
    test_surface_configuration_failures();
    test_ready_lifetime();
    test_worker_last_reference_finalization();
    puts("PASS: actual GPU attachment lifecycle");
    return 0;
}
