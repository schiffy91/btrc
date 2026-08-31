#include "btrc_app.h"
#include "btrc_app_surface_internal.h"
#include "btrc_gpu.h"
#include "fake_glfw_runtime.h"

#include <GLFW/glfw3.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <webgpu.h>

enum { LIFECYCLE_CAPACITY = 1024 };

static char lifecycle[LIFECYCLE_CAPACITY];
static unsigned long long next_future = 1;
static bool device_lost_pending;
static WGPUDeviceLostCallbackInfo device_lost_callback;
static unsigned char instance_token;
static unsigned char surface_token;
static unsigned char adapter_token;
static unsigned char device_token;
static unsigned char queue_token;
static unsigned char buffer_token;

static void require(bool condition, const char* message) {
    if (condition) { return; }
    fprintf(stderr, "integrated app/GPU runtime test failed: %s\n", message);
    abort();
}

static void record(const char* operation) {
    size_t used = strlen(lifecycle);
    size_t length = strlen(operation);
    require(used + (used == 0 ? 0 : 1) + length < sizeof(lifecycle),
            "lifecycle log overflow");
    if (used != 0) { lifecycle[used++] = ','; }
    memcpy(lifecycle + used, operation, length + 1);
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

static WGPUBuffer test_buffer(void) {
    return (WGPUBuffer)(void*)&buffer_token;
}

static WGPUStringView empty_message(void) {
    return (WGPUStringView){ .data = "", .length = 0 };
}

static WGPUFuture future(void) {
    WGPUFuture result = { .id = next_future++ };
    return result;
}

WGPUInstance integrated_gpu_create_instance(
        const WGPUInstanceDescriptor* descriptor) {
    require(descriptor == NULL, "unexpected instance descriptor");
    return test_instance();
}

WGPUSurface integrated_gpu_create_surface(
        WGPUInstance instance, GLFWwindow* window) {
    require(instance == test_instance(), "surface received wrong instance");
    require(window != NULL, "surface received null application window");
    return test_surface();
}

WGPUFuture integrated_gpu_request_adapter(
        WGPUInstance instance,
        const WGPURequestAdapterOptions* options,
        WGPURequestAdapterCallbackInfo callback_info) {
    require(instance == test_instance(), "adapter received wrong instance");
    require(options && options->compatibleSurface == test_surface(),
            "adapter received wrong compatible surface");
    require(callback_info.callback != NULL, "adapter callback is null");
    callback_info.callback(
        WGPURequestAdapterStatus_Success,
        test_adapter(),
        empty_message(),
        callback_info.userdata1,
        callback_info.userdata2);
    return future();
}

WGPUFuture integrated_gpu_request_device(
        WGPUAdapter adapter,
        const WGPUDeviceDescriptor* descriptor,
        WGPURequestDeviceCallbackInfo callback_info) {
    require(adapter == test_adapter(), "device received wrong adapter");
    require(descriptor != NULL, "device descriptor is null");
    require(callback_info.callback != NULL, "device callback is null");
    device_lost_callback = descriptor->deviceLostCallbackInfo;
    device_lost_pending = true;
    callback_info.callback(
        WGPURequestDeviceStatus_Success,
        test_device(),
        empty_message(),
        callback_info.userdata1,
        callback_info.userdata2);
    return future();
}

WGPUQueue integrated_gpu_get_queue(WGPUDevice device) {
    require(device == test_device(), "queue received wrong device");
    return test_queue();
}

WGPUStatus integrated_gpu_get_capabilities(
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
    capabilities->formatCount = 1;
    capabilities->formats = formats;
    capabilities->alphaModeCount = 1;
    capabilities->alphaModes = alpha_modes;
    return WGPUStatus_Success;
}

void integrated_gpu_free_capabilities(
        WGPUSurfaceCapabilities capabilities) {
    (void)capabilities;
}

void integrated_gpu_get_framebuffer_size(
        GLFWwindow* window, int* width, int* height) {
    require(window != NULL, "framebuffer query received null window");
    require(width != NULL && height != NULL,
            "framebuffer query outputs are null");
    *width = 128;
    *height = 96;
}

void integrated_gpu_configure_surface(
        WGPUSurface surface,
        const WGPUSurfaceConfiguration* configuration) {
    require(surface == test_surface(), "configured wrong surface");
    require(configuration && configuration->device == test_device(),
            "surface configuration received wrong device");
    record("gpu-configure");
}

void integrated_gpu_unconfigure_surface(WGPUSurface surface) {
    require(surface == test_surface(), "unconfigured wrong surface");
    record("gpu-unconfigure");
}

WGPUBuffer integrated_gpu_create_buffer(
        WGPUDevice device, const WGPUBufferDescriptor* descriptor) {
    require(device == test_device(), "buffer received wrong device");
    require(descriptor && descriptor->size >= sizeof(float),
            "buffer descriptor is invalid");
    record("uniform-create");
    return test_buffer();
}

void integrated_gpu_release_buffer(WGPUBuffer buffer) {
    require(buffer == test_buffer(), "released wrong uniform buffer");
    record("uniform-release");
}

void integrated_gpu_release_queue(WGPUQueue queue) {
    require(queue == test_queue(), "released wrong queue");
    record("queue-release");
}

void integrated_gpu_destroy_device(WGPUDevice device) {
    require(device == test_device(), "destroyed wrong device");
    require(device_lost_pending && device_lost_callback.callback != NULL,
            "device-lost callback is not pending");
    record("device-destroy");
    device_lost_callback.callback(
        &device,
        WGPUDeviceLostReason_Destroyed,
        empty_message(),
        device_lost_callback.userdata1,
        device_lost_callback.userdata2);
    device_lost_pending = false;
}

void integrated_gpu_release_device(WGPUDevice device) {
    require(device == test_device(), "released wrong device");
    record("device-release");
}

void integrated_gpu_release_adapter(WGPUAdapter adapter) {
    require(adapter == test_adapter(), "released wrong adapter");
    record("adapter-release");
}

void integrated_gpu_release_surface(WGPUSurface surface) {
    require(surface == test_surface(), "released wrong GPU surface");
    record("gpu-surface-release");
}

void integrated_gpu_release_instance(WGPUInstance instance) {
    require(instance == test_instance(), "released wrong instance");
    record("instance-release");
}

void integrated_gpu_process_events(WGPUInstance instance) {
    require(instance == test_instance(), "processed events on wrong instance");
}

typedef struct {
    unsigned long long application;
    unsigned long long application_receipt;
    unsigned long long window;
    unsigned long long window_receipt;
    unsigned long long surface;
    unsigned long long surface_receipt;
    unsigned long long gpu;
    unsigned long long gpu_receipt;
    unsigned long long uniform;
    unsigned long long uniform_receipt;
    int uniform_close;
    int gpu_close;
    int surface_close;
    int window_close;
    int application_close;
} FinalizeGraph;

static void* finalize_graph_on_worker(void* context) {
    FinalizeGraph* graph = (FinalizeGraph*)context;
    graph->uniform_close = std_gpu_uniform_destroy(
        graph->uniform, graph->uniform_receipt);
    graph->gpu_close = std_gpu_close(graph->gpu, graph->gpu_receipt);
    graph->surface_close = std_app_surface_release(
        graph->surface, graph->surface_receipt);
    graph->window_close = std_app_window_close(
        graph->window, graph->window_receipt);
    graph->application_close = std_app_close(
        graph->application, graph->application_receipt);

    std_gpu_uniform_finalize(graph->uniform, graph->uniform_receipt);
    std_gpu_finalize(graph->gpu, graph->gpu_receipt);
    std_app_surface_finalize(graph->surface, graph->surface_receipt);
    std_app_window_finalize(graph->window, graph->window_receipt);
    std_app_finalize(graph->application, graph->application_receipt);
    return NULL;
}

int main(void) {
    fake_glfw_reset();
    fake_glfw_set_lifecycle_observer(record);
    lifecycle[0] = '\0';

    FinalizeGraph graph = { 0 };
    graph.application = std_app_create(&graph.application_receipt);
    require(graph.application != 0 && graph.application_receipt != 0,
            "application creation failed");
    graph.window = std_app_window_open(
        graph.application, "integrated owner graph", 64, 48,
        &graph.window_receipt);
    require(graph.window != 0 && graph.window_receipt != 0,
            "window creation failed");
    graph.surface = std_app_surface_create(
        graph.window, &graph.surface_receipt);
    require(graph.surface != 0 && graph.surface_receipt != 0,
            "surface creation failed");
    require(std_gpu_attach_surface(
                graph.surface, &graph.gpu, &graph.gpu_receipt) ==
                BTRC_GPU_ATTACH_READY,
            "GPU attachment failed");
    require(graph.gpu != 0 && graph.gpu_receipt != 0,
            "GPU attachment did not publish ownership");
    require(std_gpu_uniform_create(
                graph.gpu, 1, &graph.uniform,
                &graph.uniform_receipt) == BTRC_GPU_RESOURCE_READY,
            "uniform creation status was not ready");
    require(graph.uniform != 0 && graph.uniform_receipt != 0,
            "uniform creation failed");
    require(strcmp(
                lifecycle,
                "init,create,gpu-configure,uniform-create") == 0,
            "unexpected initialization lifecycle");

    pthread_t worker;
    require(pthread_create(
                &worker, NULL, finalize_graph_on_worker, &graph) == 0,
            "failed to create finalizer worker");
    require(pthread_join(worker, NULL) == 0,
            "failed to join finalizer worker");
    require(graph.uniform_close == BTRC_GPU_CLOSE_NOT_OWNER_THREAD,
            "worker uniform close was not typed");
    require(graph.gpu_close == BTRC_GPU_CLOSE_NOT_OWNER_THREAD,
            "worker GPU close was not typed");
    require(graph.surface_close == BTRC_APP_ERROR_NOT_MAIN_THREAD &&
                graph.window_close == BTRC_APP_ERROR_NOT_MAIN_THREAD &&
                graph.application_close == BTRC_APP_ERROR_NOT_MAIN_THREAD,
            "worker application close was not typed");
    require(strcmp(
                lifecycle,
                "init,create,gpu-configure,uniform-create") == 0,
            "worker finalization performed native teardown");
    require(fake_glfw_live_windows() == 1 &&
                fake_glfw_wrong_thread_calls() == 0,
            "worker finalization touched GLFW");

    btrc_app_drain_owner_finalizers();
    require(strcmp(
                lifecycle,
                "init,create,gpu-configure,uniform-create,"
                "uniform-release,gpu-unconfigure,queue-release,"
                "device-destroy,device-release,adapter-release,"
                "gpu-surface-release,instance-release,destroy,terminate") == 0,
            "integrated child-to-loop teardown order changed");
    require(fake_glfw_live_windows() == 0 &&
                fake_glfw_destroy_calls() == 1 &&
                fake_glfw_terminate_calls() == 1 &&
                fake_glfw_terminate_with_live_windows() == 0,
            "owner drain did not release the application graph");
    require(!device_lost_pending,
            "owner drain retained the device-lost callback");
    require(fake_app_allocator_live() == 0,
            "owner drain leaked application state");

    require(std_gpu_uniform_destroy(
                graph.uniform, graph.uniform_receipt) ==
                BTRC_GPU_CLOSE_INVALID &&
                std_gpu_close(graph.gpu, graph.gpu_receipt) ==
                BTRC_GPU_CLOSE_INVALID &&
                std_app_surface_release(
                    graph.surface, graph.surface_receipt) ==
                BTRC_APP_ERROR_STALE_SURFACE,
            "stale finalized ownership remained live");

    unsigned long long replacement_receipt = 0;
    unsigned long long replacement = std_app_create(&replacement_receipt);
    require(replacement != 0 && replacement_receipt != 0,
            "owner drain did not unblock replacement application");
    require(std_app_close(replacement, replacement_receipt) ==
                BTRC_APP_ERROR_NONE,
            "replacement application did not close");
    require(strcmp(
                lifecycle,
                "init,create,gpu-configure,uniform-create,"
                "uniform-release,gpu-unconfigure,queue-release,"
                "device-destroy,device-release,adapter-release,"
                "gpu-surface-release,instance-release,destroy,terminate,"
                "init,terminate") == 0,
            "replacement application lifecycle changed");
    require(fake_app_allocator_live() == 0,
            "replacement application leaked state");

    puts("PASS: integrated production app/GPU finalizer graph");
    return 0;
}
