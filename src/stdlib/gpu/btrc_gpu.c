/*
 * btrc GPU Runtime — WebGPU implementation
 *
 * This file is strict C11 on every platform. The small macOS Metal/Cocoa
 * surface bridge lives in btrc_gpu_surface_macos.m.
 *
 * Links against: libwgpu_native (or Dawn), GLFW, platform frameworks, and
 * pthreads on POSIX hosts (the Windows implementation uses CRITICAL_SECTION).
 */

#include "btrc_gpu_compute_internal.h"
#include "btrc_gpu_async.h"
#include "btrc_gpu_compute_singleton.h"
#include "btrc_gpu_pending_list.h"
#include "btrc_gpu_surface.h"
#include "btrc_gpu_native_ui_internal.h"
#include "btrc_app_surface_internal.h"
#include <webgpu.h>
#include <GLFW/glfw3.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ================================================================
 * Internal structs
 * ================================================================ */

typedef struct GPUAsyncPending_ GPUAsyncPending_;
typedef struct GPURenderResource_ GPURenderResource_;

typedef struct GPU_ {
    WGPUInstance      instance;
    WGPUSurface       surface;
    WGPUAdapter       adapter;
    WGPUDevice        device;
    WGPUQueue         queue;
    WGPUTextureFormat surface_format;
    WGPUCompositeAlphaMode surface_alpha_mode;
    bool surface_configured;
    /* Per-frame state */
    WGPUCommandEncoder     encoder;
    WGPURenderPassEncoder  pass;
    WGPUTexture            frame_texture;
    WGPUTextureView        frame_view;
    BtrcAppSurfaceLease*   app_surface;
    BtrcGPUPendingList     pending_async;
    BtrcGPUAsync*          device_lost_async;
    WGPUFuture             device_lost_future;
    unsigned long long     owner_receipt;
    bool                   finalize_pending;
    struct GPU_* compute_next;
} GPU_;

typedef struct {
    WGPUShaderModule module;
} GPUShader_;

typedef struct {
    WGPURenderPipeline pipeline;
} GPURenderPipeline_;

struct GPUAsyncPending_ {
    BtrcGPUPendingLink link;
    WGPUFuture future;
    BtrcGPUAsync* async;
};

struct GPURenderResource_ {
    unsigned long long id;
    unsigned long long owner_receipt;
    int kind;
    GPU_* owner;
    void* resource;
    bool finalize_pending;
    GPURenderResource_* next;
};

enum {
    GPU_RENDER_RESOURCE_SHADER = 1,
    GPU_RENDER_RESOURCE_PIPELINE = 2,
    GPU_RENDER_RESOURCE_UNIFORM = 3,
    GPU_RENDER_RESOURCE_NATIVE_UI = 4,
};

static GPURenderResource_* render_resources = NULL;
static unsigned long long next_render_resource_id = UINT64_C(1);
static GPU_* active_render_gpu = NULL;
static unsigned long long active_render_gpu_id = 0;
static unsigned long long next_render_gpu_id = UINT64_C(1);
static GPU_* compute_gpus = NULL;
static _Atomic(void*) btrc_compute_singleton = NULL;

#ifdef _WIN32
static SRWLOCK render_lock = SRWLOCK_INIT;
#else
static pthread_mutex_t render_lock = PTHREAD_MUTEX_INITIALIZER;
#endif

static void render_lock_enter(void) {
#ifdef _WIN32
    AcquireSRWLockExclusive(&render_lock);
#else
    (void)pthread_mutex_lock(&render_lock);
#endif
}

static void render_lock_leave(void) {
#ifdef _WIN32
    ReleaseSRWLockExclusive(&render_lock);
#else
    (void)pthread_mutex_unlock(&render_lock);
#endif
}

static void destroy_render_resources(GPU_* gpu);
static void destroy_gpu_unchecked(GPU_* gpu);
static void drain_gpu_finalizers_locked(void);
static void btrc_gpu_drain_owner_finalizers(void);
static bool device_is_lost(GPU_* gpu);

/* The active pointer is compared before dereferencing a caller-provided GPU
 * capability.  Holding render_lock makes stale/concurrent close calls reject
 * without racing the allocation lifetime. */
static GPU_* render_gpu_locked(unsigned long long id) {
    if (id == 0 || id != active_render_gpu_id || !active_render_gpu ||
        !active_render_gpu->app_surface ||
        !std_app_surface_glfw(active_render_gpu->app_surface)) {
        return NULL;
    }
    return active_render_gpu;
}

static int render_gpu_resource_status_locked(
        unsigned long long id, GPU_** gpu_out) {
    if (gpu_out) { *gpu_out = NULL; }
    if (!gpu_out || id == 0 || id != active_render_gpu_id ||
        !active_render_gpu || !active_render_gpu->app_surface) {
        return BTRC_GPU_RESOURCE_INVALID_GPU;
    }
    if (!std_app_surface_glfw(active_render_gpu->app_surface)) {
        return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD;
    }
    *gpu_out = active_render_gpu;
    if (device_is_lost(active_render_gpu)) {
        *gpu_out = NULL;
        return BTRC_GPU_RESOURCE_DEVICE_LOST;
    }
    return BTRC_GPU_RESOURCE_READY;
}

static bool render_owner_pointer_locked(GPU_* gpu) {
    return gpu && gpu == active_render_gpu && gpu->app_surface &&
        std_app_surface_glfw(gpu->app_surface) != NULL;
}

static unsigned long long new_render_gpu_capability(void) {
    unsigned long long id = next_render_gpu_id++;
    if (id == 0) { id = next_render_gpu_id++; }
    return id;
}

/* Native WebGPU requests are asynchronous even though the btrc wrapper exposes
 * synchronous construction/readback.  Bound every such bridge so a wedged
 * driver cannot hang the process forever. */
static const unsigned long long gpu_async_timeout_ns = UINT64_C(30000000000);
static const unsigned long long gpu_async_cancel_drain_timeout_ns = UINT64_C(100000000);

static void discard_frame(GPU_* gpu) {
    if (!gpu) { return; }
    if (gpu->pass) {
        wgpuRenderPassEncoderEnd(gpu->pass);
        wgpuRenderPassEncoderRelease(gpu->pass);
        gpu->pass = NULL;
    }
    if (gpu->encoder) {
        wgpuCommandEncoderRelease(gpu->encoder);
        gpu->encoder = NULL;
    }
    if (gpu->frame_view) {
        wgpuTextureViewRelease(gpu->frame_view);
        gpu->frame_view = NULL;
    }
    if (gpu->frame_texture) {
        wgpuTextureRelease(gpu->frame_texture);
        gpu->frame_texture = NULL;
    }
}

static WGPUInstance create_gpu_instance(void) {
    /* Timed WaitAny is optional and some native implementations abort instead
     * of returning an unsupported-feature status when it is requested. The
     * async bridge uses zero-timeout exact-future polling where implemented;
     * the explicit wgpu-native build uses synchronized ProcessEvents. */
    return wgpuCreateInstance(NULL);
}

/* ================================================================
 * Async request helpers
 * ================================================================ */

static void on_adapter(WGPURequestAdapterStatus status, WGPUAdapter adapter,
                       WGPUStringView message, void* ud1, void* ud2) {
    (void)message; (void)ud2;
    btrc_gpu_async_complete(
        (BtrcGPUAsync*)ud1, (int)status, (void*)adapter);
}

static void on_device(WGPURequestDeviceStatus status, WGPUDevice device,
                      WGPUStringView message, void* ud1, void* ud2) {
    (void)message; (void)ud2;
    btrc_gpu_async_complete(
        (BtrcGPUAsync*)ud1, (int)status, (void*)device);
}

static void on_device_lost(
        WGPUDevice const* device,
        WGPUDeviceLostReason reason,
        WGPUStringView message,
        void* ud1,
        void* ud2) {
    (void)device;
    (void)message;
    (void)ud2;
    btrc_gpu_async_complete((BtrcGPUAsync*)ud1, (int)reason, NULL);
}

static void release_adapter_result(void* result) {
    if (result) { wgpuAdapterRelease((WGPUAdapter)result); }
}

static void release_device_result(void* result) {
    if (result) { wgpuDeviceRelease((WGPUDevice)result); }
}

static bool request_adapter(GPU_* gpu,
                            const WGPURequestAdapterOptions* options) {
    BtrcGPUAsync* async = btrc_gpu_async_create(release_adapter_result);
    if (!async) { return false; }
    WGPUFuture future = wgpuInstanceRequestAdapter(
        gpu->instance, options,
        (WGPURequestAdapterCallbackInfo){
            .mode = BTRC_GPU_ASYNC_CALLBACK_MODE,
            .callback = on_adapter,
            .userdata1 = async,
        });
    int status = 0;
    void* result = NULL;
    BtrcGPUAsyncWaitOutcome outcome = btrc_gpu_async_wait(
        gpu->instance, future, async, gpu_async_timeout_ns, &status, &result);
    /* On timeout/error, the callback reference survives until immediate caller
     * teardown drops the instance and delivers CallbackCancelled. */
    btrc_gpu_async_release(async);
    if (outcome != BTRC_GPU_ASYNC_COMPLETED ||
        status != (int)WGPURequestAdapterStatus_Success ||
        !result) {
        release_adapter_result(result);
        fprintf(stderr,
                "[btrc-gpu] adapter request failed: wait=%d status=%d\n",
                (int)outcome, status);
        return false;
    }
    gpu->adapter = (WGPUAdapter)result;
    return true;
}

static bool request_device(GPU_* gpu, const WGPUDeviceDescriptor* descriptor) {
    BtrcGPUAsync* async = btrc_gpu_async_create(release_device_result);
    if (!async) { return false; }
    BtrcGPUAsync* lost_async = btrc_gpu_async_create(NULL);
    if (!lost_async) {
        /* No request published async's reserved callback reference. Drop both
         * that reference and the synchronous caller reference. */
        btrc_gpu_async_release(async);
        btrc_gpu_async_release(async);
        return false;
    }
    WGPUDeviceDescriptor configured = descriptor
        ? *descriptor : (WGPUDeviceDescriptor){ 0 };
    configured.deviceLostCallbackInfo = (WGPUDeviceLostCallbackInfo){
        .mode = BTRC_GPU_ASYNC_CALLBACK_MODE,
        .callback = on_device_lost,
        .userdata1 = lost_async,
    };
    WGPUFuture future = wgpuAdapterRequestDevice(
        gpu->adapter, &configured,
        (WGPURequestDeviceCallbackInfo){
            .mode = BTRC_GPU_ASYNC_CALLBACK_MODE,
            .callback = on_device,
            .userdata1 = async,
        });
    int status = 0;
    void* result = NULL;
    BtrcGPUAsyncWaitOutcome outcome = btrc_gpu_async_wait(
        gpu->instance, future, async, gpu_async_timeout_ns, &status, &result);
    /* The callback reference remains valid through instance cancellation. */
    btrc_gpu_async_release(async);
    if (outcome != BTRC_GPU_ASYNC_COMPLETED ||
        status != (int)WGPURequestDeviceStatus_Success ||
        !result) {
        release_device_result(result);
        btrc_gpu_async_release(lost_async);
        fprintf(stderr,
                "[btrc-gpu] device request failed: wait=%d status=%d\n",
                (int)outcome, status);
        return false;
    }
    gpu->device = (WGPUDevice)result;
    gpu->device_lost_async = lost_async;
#ifdef BTRC_GPU_WGPU_NATIVE
    /* wgpu-native 27 aborts in its exported GetLostFuture stub. Its
     * AllowProcessEvents callback is polled directly by device_is_lost(). */
    gpu->device_lost_future = (WGPUFuture){ 0 };
#else
    gpu->device_lost_future = wgpuDeviceGetLostFuture(gpu->device);
#endif
    return true;
}

static bool device_is_lost(GPU_* gpu) {
    if (!gpu || !gpu->device || !gpu->instance ||
        !gpu->device_lost_async) {
        return false;
    }
    return btrc_gpu_async_wait(
        gpu->instance,
        gpu->device_lost_future,
        gpu->device_lost_async,
        0,
        NULL,
        NULL) == BTRC_GPU_ASYNC_COMPLETED;
}

/* A WaitAnyOnly callback runs only while its exact future is polled. Keep the
 * synchronous reference and future after a readback timeout so later GPU work
 * can reap the small callback state. The staging handle itself is released as
 * soon as unmap requests cancellation. */
static void reap_pending_async(GPU_* gpu) {
    if (!gpu || !gpu->instance) { return; }
    BtrcGPUPendingLink* links =
        btrc_gpu_pending_list_take_all(&gpu->pending_async);
    BtrcGPUPendingLink* unreaped = NULL;
    while (links) {
        BtrcGPUPendingLink* next = links->next;
        GPUAsyncPending_* pending = (GPUAsyncPending_*)links;
        BtrcGPUAsyncWaitOutcome outcome = btrc_gpu_async_wait(
            gpu->instance, pending->future, pending->async, 0, NULL, NULL);
        if (outcome != BTRC_GPU_ASYNC_COMPLETED) {
            links->next = unreaped;
            unreaped = links;
        } else {
            btrc_gpu_async_release(pending->async);
            free(pending);
        }
        links = next;
    }
    btrc_gpu_pending_list_merge(&gpu->pending_async, unreaped);
}

static void release_pending_async_callers(GPU_* gpu) {
    BtrcGPUPendingLink* links = gpu
        ? btrc_gpu_pending_list_take_all(&gpu->pending_async) : NULL;
    while (links) {
        BtrcGPUPendingLink* next = links->next;
        GPUAsyncPending_* pending = (GPUAsyncPending_*)links;
        /* Instance destruction requests callback cancellation. If a backend
         * delivers it later, the callback's own reference still protects the
         * userdata after this synchronous ownership is released. */
        btrc_gpu_async_release(pending->async);
        free(pending);
        links = next;
    }
}

/* ================================================================
 * GPU attachment
 * ================================================================ */

static int attach_surface_locked(unsigned long long surface_id, void** gpu_out) {
    if (!gpu_out) { return BTRC_GPU_ATTACH_INVALID_SURFACE; }
    *gpu_out = NULL;
    BtrcAppSurfaceLease* lease = NULL;
    int app_status = std_app_surface_attach(surface_id, &lease);
    if (app_status != BTRC_APP_ERROR_NONE || !lease) {
        switch (app_status) {
            case BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED:
                return BTRC_GPU_ATTACH_SURFACE_BUSY;
            case BTRC_APP_ERROR_NOT_MAIN_THREAD:
                return BTRC_GPU_ATTACH_NOT_OWNER_THREAD;
            case BTRC_APP_ERROR_INTERNAL:
                return BTRC_GPU_ATTACH_INTERNAL_ERROR;
            default:
                return BTRC_GPU_ATTACH_INVALID_SURFACE;
        }
    }
    GLFWwindow* window = std_app_surface_glfw(lease);
    if (!window) {
        std_app_surface_detach(lease);
        return BTRC_GPU_ATTACH_INVALID_SURFACE;
    }
    GPU_* gpu = (GPU_*)calloc(1, sizeof(GPU_));
    if (!gpu) {
        std_app_surface_detach(lease);
        return BTRC_GPU_ATTACH_OUT_OF_MEMORY;
    }
    if (!btrc_gpu_pending_list_init(&gpu->pending_async)) {
        std_app_surface_detach(lease);
        free(gpu);
        return BTRC_GPU_ATTACH_INTERNAL_ERROR;
    }
    gpu->app_surface = lease;
    int failure = BTRC_GPU_ATTACH_INTERNAL_ERROR;

    /* Instance */
    gpu->instance = create_gpu_instance();
    if (!gpu->instance) {
        fprintf(stderr, "[btrc-gpu] wgpuCreateInstance failed\n");
        goto attach_failed;
    }

    gpu->surface = btrc_gpu_create_surface(gpu->instance, window);
    if (!gpu->surface) {
        fprintf(stderr, "[btrc-gpu] surface creation failed\n");
        failure = BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED;
        goto attach_failed;
    }

    /* Conforming backends wait on this exact future; wgpu-native serializes
     * event pumping and publishes callback state atomically. */
    WGPURequestAdapterOptions adapter_opts = {
        .compatibleSurface = gpu->surface,
        .featureLevel = WGPUFeatureLevel_Core,
    };
    if (!request_adapter(gpu, &adapter_opts)) {
        fprintf(stderr, "[btrc-gpu] no suitable GPU adapter found\n");
        failure = BTRC_GPU_ATTACH_ADAPTER_UNAVAILABLE;
        goto attach_failed;
    }

    /* Likewise, keep the device callback on this thread before returning. */
    if (!request_device(gpu, NULL)) {
        fprintf(stderr, "[btrc-gpu] device request failed\n");
        failure = BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE;
        goto attach_failed;
    }

    /* Queue */
    gpu->queue = wgpuDeviceGetQueue(gpu->device);
    if (!gpu->queue) {
        failure = BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE;
        goto attach_failed;
    }

    /* Surface format + configure */
    WGPUSurfaceCapabilities caps = { 0 };
    if (wgpuSurfaceGetCapabilities(gpu->surface, gpu->adapter, &caps) !=
            WGPUStatus_Success ||
        caps.formatCount == 0 || !caps.formats ||
        caps.alphaModeCount == 0 || !caps.alphaModes) {
        wgpuSurfaceCapabilitiesFreeMembers(caps);
        failure = BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED;
        goto attach_failed;
    }
    gpu->surface_format = caps.formats[0];
    gpu->surface_alpha_mode = caps.alphaModes[0];

    int width = 0;
    int height = 0;
    glfwGetFramebufferSize(window, &width, &height);
    if (width <= 0 || height <= 0) {
        wgpuSurfaceCapabilitiesFreeMembers(caps);
        failure = BTRC_GPU_ATTACH_INVALID_SURFACE;
        goto attach_failed;
    }
    WGPUSurfaceConfiguration config = {
        .device      = gpu->device,
        .usage       = WGPUTextureUsage_RenderAttachment,
        .format      = gpu->surface_format,
        .presentMode = WGPUPresentMode_Fifo,
        .alphaMode   = gpu->surface_alpha_mode,
        .width       = (uint32_t)width,
        .height      = (uint32_t)height,
    };
    wgpuSurfaceConfigure(gpu->surface, &config);
    gpu->surface_configured = true;
    wgpuSurfaceCapabilitiesFreeMembers(caps);

    *gpu_out = gpu;
    return BTRC_GPU_ATTACH_READY;

attach_failed:
    /* Every acquired native child and the application-surface lease unwind
     * through one ownership path, including partially initialized devices. */
    destroy_gpu_unchecked(gpu);
    return failure;
}

int std_gpu_attach_surface(
        unsigned long long surface_id,
        unsigned long long* gpu_out,
        unsigned long long* owner_receipt_out) {
    if (!gpu_out || !owner_receipt_out) {
        return BTRC_GPU_ATTACH_INVALID_SURFACE;
    }
    *gpu_out = 0;
    *owner_receipt_out = 0;
    render_lock_enter();
    drain_gpu_finalizers_locked();
    if (active_render_gpu) {
        render_lock_leave();
        return BTRC_GPU_ATTACH_SURFACE_BUSY;
    }
    void* native_gpu = NULL;
    int status = attach_surface_locked(surface_id, &native_gpu);
    if (status == BTRC_GPU_ATTACH_READY && native_gpu) {
        active_render_gpu = (GPU_*)native_gpu;
        active_render_gpu_id = new_render_gpu_capability();
        active_render_gpu->owner_receipt = new_render_gpu_capability();
        *gpu_out = active_render_gpu_id;
        *owner_receipt_out = active_render_gpu->owner_receipt;
        btrc_app_register_owner_drain_hook(
            btrc_gpu_drain_owner_finalizers);
    } else if (native_gpu) {
        destroy_gpu_unchecked((GPU_*)native_gpu);
        status = BTRC_GPU_ATTACH_INTERNAL_ERROR;
    } else if (status == BTRC_GPU_ATTACH_READY) {
        status = BTRC_GPU_ATTACH_INTERNAL_ERROR;
    }
    render_lock_leave();
    return status;
}

char* std_gpu_status_message(int status) {
    switch (status) {
        case BTRC_GPU_ATTACH_READY: return "";
        case BTRC_GPU_ATTACH_INVALID_SURFACE: return "invalid or stale application surface";
        case BTRC_GPU_ATTACH_SURFACE_BUSY: return "application surface already has a GPU owner";
        case BTRC_GPU_ATTACH_ADAPTER_UNAVAILABLE: return "no compatible GPU adapter";
        case BTRC_GPU_ATTACH_DEVICE_UNAVAILABLE: return "GPU device request failed";
        case BTRC_GPU_ATTACH_SURFACE_UNSUPPORTED: return "GPU surface is unsupported";
        case BTRC_GPU_ATTACH_OUT_OF_MEMORY: return "GPU allocation failed";
        case BTRC_GPU_ATTACH_NOT_OWNER_THREAD: return "GPU operation requires the application owner thread";
        case BTRC_GPU_FRAME_TIMEOUT: return "GPU surface acquisition timed out";
        case BTRC_GPU_FRAME_OUTDATED: return "GPU surface is outdated";
        case BTRC_GPU_FRAME_SURFACE_LOST: return "GPU surface was lost";
        case BTRC_GPU_FRAME_OUT_OF_MEMORY: return "GPU is out of memory";
        case BTRC_GPU_FRAME_DEVICE_LOST: return "GPU device was lost";
        case BTRC_GPU_FRAME_REJECTED: return "GPU frame was rejected";
        case BTRC_GPU_CLOSE_CLOSED: return "";
        case BTRC_GPU_CLOSE_NOT_OWNER_THREAD: return "GPU close requires the application owner thread";
        case BTRC_GPU_CLOSE_INVALID: return "GPU is not open";
        case BTRC_GPU_RESOURCE_READY: return "";
        case BTRC_GPU_RESOURCE_INVALID_GPU: return "GPU is not open";
        case BTRC_GPU_RESOURCE_NOT_OWNER_THREAD: return "GPU resource operation requires the application owner thread";
        case BTRC_GPU_RESOURCE_DEVICE_LOST: return "GPU device was lost";
        case BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR: return "GPU resource descriptor is invalid";
        case BTRC_GPU_RESOURCE_INVALID_RESOURCE: return "GPU resource is invalid, stale, or owned by another GPU";
        case BTRC_GPU_RESOURCE_CREATION_FAILED: return "GPU backend rejected resource creation";
        case BTRC_GPU_RESOURCE_OUT_OF_MEMORY: return "GPU resource ownership allocation failed";
        case BTRC_GPU_RESOURCE_INTERNAL_ERROR: return "GPU resource operation returned an invalid result";
        case BTRC_GPU_DRAW_RECORDED: return "";
        case BTRC_GPU_DRAW_INVALID_GPU: return "GPU is not open";
        case BTRC_GPU_DRAW_NOT_OWNER_THREAD: return "GPU draw requires the application owner thread";
        case BTRC_GPU_DRAW_DEVICE_LOST: return "GPU device was lost";
        case BTRC_GPU_DRAW_INVALID_DESCRIPTOR: return "GPU draw descriptor is invalid";
        case BTRC_GPU_DRAW_INVALID_RESOURCE: return "GPU draw resource is invalid, stale, or owned by another GPU";
        case BTRC_GPU_DRAW_NO_ACTIVE_FRAME: return "GPU draw requires an active frame";
        case BTRC_GPU_DRAW_BACKEND_FAILURE: return "GPU backend rejected the draw command";
        default: return "internal GPU error";
    }
}

int std_gpu_close(
        unsigned long long gpu,
        unsigned long long owner_receipt) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* owner = render_gpu_locked(gpu);
    if (owner && (owner_receipt == 0 ||
                  owner->owner_receipt != owner_receipt)) {
        owner = NULL;
    }
    if (!owner) {
        bool exact_owner = gpu != 0 && gpu == active_render_gpu_id &&
            active_render_gpu != NULL && owner_receipt != 0 &&
            active_render_gpu->owner_receipt == owner_receipt;
        bool wrong_thread = exact_owner &&
            render_gpu_locked(gpu) == NULL;
        render_lock_leave();
        return wrong_thread
            ? BTRC_GPU_CLOSE_NOT_OWNER_THREAD : BTRC_GPU_CLOSE_INVALID;
    }
    active_render_gpu = NULL;
    active_render_gpu_id = 0;
    destroy_gpu_unchecked(owner);
    render_lock_leave();
    /* Detaching the application surface may have unblocked deferred surface,
     * window, and application finalizers. Retry them only after releasing the
     * render lock so the established render -> app lock order is preserved. */
    btrc_app_drain_owner_finalizers();
    return BTRC_GPU_CLOSE_CLOSED;
}

void std_gpu_finalize(
        unsigned long long gpu,
        unsigned long long owner_receipt) {
    render_lock_enter();
    if (gpu != 0 && gpu == active_render_gpu_id && active_render_gpu &&
        owner_receipt != 0 &&
        active_render_gpu->owner_receipt == owner_receipt) {
        active_render_gpu->finalize_pending = true;
    }
    render_lock_leave();
    btrc_gpu_drain_owner_finalizers();
}

void btrc_gpu_destroy(void* gpu_) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu) return;
    /* The compiler-wide compute context is process-lifetime shared state.
     * Candidate losers are destroyable, but a published winner must never be
     * retired while generated dispatch helpers can still acquire it. */
    if (gpu_ == atomic_load_explicit(
            &btrc_compute_singleton, memory_order_acquire)) {
        return;
    }
    render_lock_enter();
    GPU_** link = &compute_gpus;
    while (*link && *link != gpu) { link = &(*link)->compute_next; }
    if (!*link) {
        render_lock_leave();
        return;
    }
    *link = gpu->compute_next;
    gpu->compute_next = NULL;
    render_lock_leave();
    /* Only registered compute candidates reach the raw hosted deallocator.
     * Render ownership is closed exclusively through its integer capability. */
    destroy_gpu_unchecked(gpu);
}

static void destroy_gpu_unchecked(GPU_* gpu) {
    if (!gpu) { return; }
    reap_pending_async(gpu);
    discard_frame(gpu);
    if (gpu->app_surface) { destroy_render_resources(gpu); }
    if (gpu->surface && gpu->surface_configured) {
        wgpuSurfaceUnconfigure(gpu->surface);
        gpu->surface_configured = false;
    }
    if (gpu->queue)    wgpuQueueRelease(gpu->queue);
    if (gpu->device) {
        wgpuDeviceDestroy(gpu->device);
        (void)device_is_lost(gpu);
        wgpuDeviceRelease(gpu->device);
    }
    if (gpu->adapter)  wgpuAdapterRelease(gpu->adapter);
    if (gpu->surface)  wgpuSurfaceRelease(gpu->surface);
    if (gpu->instance) {
        wgpuInstanceRelease(gpu->instance);
        gpu->instance = NULL;
    }
    btrc_gpu_async_release(gpu->device_lost_async);
    release_pending_async_callers(gpu);
    if (!btrc_gpu_pending_list_destroy(&gpu->pending_async)) {
        fprintf(stderr, "[btrc-gpu] pending-list mutex destroy failed\n");
    }
    if (gpu->app_surface) {
        (void)std_app_surface_detach(gpu->app_surface);
    }
    free(gpu);
}

/* ================================================================
 * Shader
 * ================================================================ */

void* btrc_gpu_create_shader(void* gpu_, char* wgsl_source) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu || !gpu->device || !wgsl_source) { return NULL; }
    WGPUShaderSourceWGSL wgsl = {
        .chain = { .sType = WGPUSType_ShaderSourceWGSL },
        .code  = { .data = wgsl_source, .length = strlen(wgsl_source) },
    };
    WGPUShaderModuleDescriptor desc = {
        .nextInChain = (WGPUChainedStruct*)&wgsl,
    };
    WGPUShaderModule mod = wgpuDeviceCreateShaderModule(gpu->device, &desc);
    if (!mod) {
        fprintf(stderr, "[btrc-gpu] shader compilation failed\n");
        return NULL;
    }

    GPUShader_* s = (GPUShader_*)calloc(1, sizeof(GPUShader_));
    if (!s) {
        wgpuShaderModuleRelease(mod);
        return NULL;
    }
    s->module = mod;
    return s;
}

void btrc_gpu_shader_destroy(void* s_) {
    GPUShader_* s = (GPUShader_*)s_;
    if (!s) return;
    if (s->module) wgpuShaderModuleRelease(s->module);
    free(s);
}

/* ================================================================
 * Render Pipeline
 * ================================================================ */

void* btrc_gpu_create_render_pipeline(
        void* gpu_, void* shader_,
        char* vertex_entry, char* fragment_entry) {

    GPU_* gpu = (GPU_*)gpu_;
    GPUShader_* shader = (GPUShader_*)shader_;
    if (!gpu || !gpu->device || !shader || !shader->module ||
        !vertex_entry || !fragment_entry) {
        return NULL;
    }

    WGPURenderPipelineDescriptor desc = {
        .vertex = {
            .module     = shader->module,
            .entryPoint = { .data = vertex_entry, .length = strlen(vertex_entry) },
        },
        .fragment = &(WGPUFragmentState){
            .module      = shader->module,
            .entryPoint  = { .data = fragment_entry, .length = strlen(fragment_entry) },
            .targetCount = 1,
            .targets     = (WGPUColorTargetState[]){
                {
                    .format    = gpu->surface_format,
                    .writeMask = WGPUColorWriteMask_All,
                },
            },
        },
        .primitive = {
            .topology = WGPUPrimitiveTopology_TriangleList,
        },
        .multisample = {
            .count = 1,
            .mask  = 0xFFFFFFFF,
        },
    };

    WGPURenderPipeline rp = wgpuDeviceCreateRenderPipeline(gpu->device, &desc);
    if (!rp) {
        fprintf(stderr, "[btrc-gpu] render pipeline creation failed\n");
        return NULL;
    }

    GPURenderPipeline_* p = (GPURenderPipeline_*)calloc(1, sizeof(GPURenderPipeline_));
    if (!p) {
        wgpuRenderPipelineRelease(rp);
        return NULL;
    }
    p->pipeline = rp;
    return p;
}

void btrc_gpu_pipeline_destroy(void* p_) {
    GPURenderPipeline_* p = (GPURenderPipeline_*)p_;
    if (!p) return;
    if (p->pipeline) wgpuRenderPipelineRelease(p->pipeline);
    free(p);
}

/* ================================================================
 * Frame rendering
 * ================================================================ */

static int begin_frame_locked(GPU_* gpu, float r, float g, float b, float a) {
    reap_pending_async(gpu);
    if (device_is_lost(gpu)) { return BTRC_GPU_FRAME_DEVICE_LOST; }
    GLFWwindow* window = std_app_surface_glfw(gpu->app_surface);
    if (!gpu->surface || !gpu->device || !window ||
        gpu->pass || gpu->encoder || gpu->frame_texture ||
        gpu->frame_view) {
        return BTRC_GPU_FRAME_REJECTED;
    }

    /* Get current surface texture */
    WGPUSurfaceTexture st = { 0 };
    wgpuSurfaceGetCurrentTexture(gpu->surface, &st);

    if (st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal &&
        st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessSuboptimal) {
        if (st.texture) wgpuTextureRelease(st.texture);
        if (st.status == WGPUSurfaceGetCurrentTextureStatus_Outdated) {
            int w = 0;
            int h = 0;
            glfwGetFramebufferSize(window, &w, &h);
            if (w > 0 && h > 0) {
                WGPUSurfaceConfiguration config = {
                    .device      = gpu->device,
                    .usage       = WGPUTextureUsage_RenderAttachment,
                    .format      = gpu->surface_format,
                    .presentMode = WGPUPresentMode_Fifo,
                    .alphaMode   = gpu->surface_alpha_mode,
                    .width       = (uint32_t)w,
                    .height      = (uint32_t)h,
                };
                wgpuSurfaceConfigure(gpu->surface, &config);
            }
        }
        switch (st.status) {
            case WGPUSurfaceGetCurrentTextureStatus_Timeout:
                return BTRC_GPU_FRAME_TIMEOUT;
            case WGPUSurfaceGetCurrentTextureStatus_Outdated:
                return BTRC_GPU_FRAME_OUTDATED;
            case WGPUSurfaceGetCurrentTextureStatus_Lost:
                return BTRC_GPU_FRAME_SURFACE_LOST;
            case WGPUSurfaceGetCurrentTextureStatus_OutOfMemory:
                return BTRC_GPU_FRAME_OUT_OF_MEMORY;
            case WGPUSurfaceGetCurrentTextureStatus_DeviceLost:
                return BTRC_GPU_FRAME_DEVICE_LOST;
            default:
                return BTRC_GPU_FRAME_REJECTED;
        }
    }
    if (!st.texture) { return BTRC_GPU_FRAME_REJECTED; }

    gpu->frame_texture = st.texture;
    gpu->frame_view = wgpuTextureCreateView(st.texture, NULL);
    if (!gpu->frame_view) {
        discard_frame(gpu);
        return BTRC_GPU_FRAME_REJECTED;
    }

    /* Command encoder */
    gpu->encoder = wgpuDeviceCreateCommandEncoder(gpu->device, NULL);
    if (!gpu->encoder) {
        discard_frame(gpu);
        return BTRC_GPU_FRAME_REJECTED;
    }

    /* Begin render pass */
    WGPURenderPassColorAttachment color_att = {
        .view       = gpu->frame_view,
        .loadOp     = WGPULoadOp_Clear,
        .storeOp    = WGPUStoreOp_Store,
        .depthSlice = WGPU_DEPTH_SLICE_UNDEFINED,
        .clearValue = { .r = r, .g = g, .b = b, .a = a },
    };
    WGPURenderPassDescriptor rp_desc = {
        .colorAttachmentCount = 1,
        .colorAttachments     = &color_att,
    };
    gpu->pass = wgpuCommandEncoderBeginRenderPass(gpu->encoder, &rp_desc);
    if (!gpu->pass) {
        discard_frame(gpu);
        return BTRC_GPU_FRAME_REJECTED;
    }
    return BTRC_GPU_FRAME_READY;
}

int std_gpu_begin_frame(unsigned long long gpu_id, float r, float g, float b, float a) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = render_gpu_locked(gpu_id);
    if (!gpu) {
        render_lock_leave();
        return BTRC_GPU_FRAME_REJECTED;
    }
    int result = begin_frame_locked(gpu, r, g, b, a);
    render_lock_leave();
    return result;
}

bool btrc_gpu_begin_frame(void* gpu_, float r, float g, float b, float a) {
    GPU_* gpu = (GPU_*)gpu_;
    render_lock_enter();
    bool ready = render_owner_pointer_locked(gpu) &&
        begin_frame_locked(gpu, r, g, b, a) == BTRC_GPU_FRAME_READY;
    render_lock_leave();
    return ready;
}

void btrc_gpu_draw(void* gpu_, void* pipeline_, int vertex_count) {
    GPU_* gpu = (GPU_*)gpu_;
    GPURenderPipeline_* pipeline = (GPURenderPipeline_*)pipeline_;
    if (!gpu || !gpu->pass || !pipeline || !pipeline->pipeline ||
        vertex_count <= 0) {
        return;
    }
    wgpuRenderPassEncoderSetPipeline(gpu->pass, pipeline->pipeline);
    wgpuRenderPassEncoderDraw(gpu->pass, (uint32_t)vertex_count, 1, 0, 0);
}

static int finish_frame(GPU_* gpu) {
    if (device_is_lost(gpu)) {
        discard_frame(gpu);
        return BTRC_GPU_FRAME_DEVICE_LOST;
    }
    if (!gpu || !gpu->pass || !gpu->encoder || !gpu->frame_view ||
        !gpu->frame_texture) {
        discard_frame(gpu);
        return BTRC_GPU_FRAME_REJECTED;
    }

    wgpuRenderPassEncoderEnd(gpu->pass);
    wgpuRenderPassEncoderRelease(gpu->pass);
    gpu->pass = NULL;

    WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(gpu->encoder, NULL);
    if (!cmd) {
        discard_frame(gpu);
        return BTRC_GPU_FRAME_REJECTED;
    }
    wgpuQueueSubmit(gpu->queue, 1, &cmd);
    WGPUStatus present_status = wgpuSurfacePresent(gpu->surface);
    wgpuCommandBufferRelease(cmd);

    wgpuCommandEncoderRelease(gpu->encoder);
    wgpuTextureViewRelease(gpu->frame_view);
    wgpuTextureRelease(gpu->frame_texture);

    gpu->encoder       = NULL;
    gpu->frame_view    = NULL;
    gpu->frame_texture = NULL;
    if (device_is_lost(gpu)) { return BTRC_GPU_FRAME_DEVICE_LOST; }
    return present_status == WGPUStatus_Success
        ? BTRC_GPU_FRAME_PRESENTED : BTRC_GPU_FRAME_REJECTED;
}

void btrc_gpu_end_frame(void* gpu_) {
    GPU_* gpu = (GPU_*)gpu_;
    render_lock_enter();
    if (render_owner_pointer_locked(gpu)) { (void)finish_frame(gpu); }
    render_lock_leave();
}

int std_gpu_end_frame(unsigned long long gpu_id) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = render_gpu_locked(gpu_id);
    if (!gpu) {
        render_lock_leave();
        return BTRC_GPU_FRAME_REJECTED;
    }
    int result = finish_frame(gpu);
    render_lock_leave();
    return result;
}

/* ================================================================
 * Headless compute (no window/surface needed)
 * ================================================================ */

void* btrc_gpu_init_compute(void) {
    GPU_* gpu = (GPU_*)calloc(1, sizeof(GPU_));
    if (!gpu) { return NULL; }
    if (!btrc_gpu_pending_list_init(&gpu->pending_async)) {
        free(gpu);
        return NULL;
    }
    gpu->app_surface = NULL;
    gpu->surface = NULL;

    gpu->instance = create_gpu_instance();
    if (!gpu->instance) {
        /* Non-fatal: callers probe via btrc_gpu_available() and fall back to CPU. */
        destroy_gpu_unchecked(gpu);
        return NULL;
    }

    WGPURequestAdapterOptions adapter_opts = {
        .featureLevel = WGPUFeatureLevel_Core,
    };
    if (!request_adapter(gpu, &adapter_opts)) {
        destroy_gpu_unchecked(gpu);
        return NULL;
    }

    /* Request the adapter's full supported limits so large (image-sized)
     * storage buffers are allowed — the default maxStorageBufferBindingSize
     * (128 MB) is too small for full-resolution photo buffers. */
    WGPULimits limits = { 0 };
    WGPUDeviceDescriptor dev_desc = { 0 };
    if (wgpuAdapterGetLimits(gpu->adapter, &limits) == WGPUStatus_Success) {
        dev_desc.requiredLimits = &limits;
    }
    if (!request_device(gpu, &dev_desc)) {
        destroy_gpu_unchecked(gpu);
        return NULL;
    }

    gpu->queue = wgpuDeviceGetQueue(gpu->device);
    if (!gpu->queue) {
        destroy_gpu_unchecked(gpu);
        return NULL;
    }
    render_lock_enter();
    gpu->compute_next = compute_gpus;
    compute_gpus = gpu;
    render_lock_leave();
    return gpu;
}

/* Process-lifetime compute context. Device and queue handles are safe to use
 * from concurrent callers; per-dispatch buffers and pipelines remain local. */

void* btrc_gpu_acquire_compute(void) {
    if (getenv("BTRC_NO_GPU")) { return NULL; }
    void* current = atomic_load_explicit(
        &btrc_compute_singleton, memory_order_acquire);
    if (current) { return current; }

    void* candidate = btrc_gpu_init_compute();
    if (!candidate) { return NULL; }
    return btrc_gpu_publish_compute_candidate(
        &btrc_compute_singleton, candidate, btrc_gpu_destroy);
}

/* Non-fatal probe used by source code and generated dispatch helpers. */
bool btrc_gpu_available(void) {
    return btrc_gpu_acquire_compute() != NULL;
}

/* ================================================================
 * Buffers
 * ================================================================ */

void* btrc_gpu_create_buffer(void* gpu_, int size, int usage) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu || !gpu->device || size <= 0) { return NULL; }
    WGPUBufferUsage wgpu_usage = 0;
    if (usage & 0x80) wgpu_usage |= WGPUBufferUsage_Storage;
    if (usage & 0x40) wgpu_usage |= WGPUBufferUsage_Uniform;
    if (usage & 0x08) wgpu_usage |= WGPUBufferUsage_CopyDst;
    if (usage & 0x04) wgpu_usage |= WGPUBufferUsage_CopySrc;
    if (wgpu_usage == 0) { return NULL; }

    WGPUBufferDescriptor desc = {
        .size            = (unsigned long long)size,
        .usage           = wgpu_usage,
        .mappedAtCreation = false,
    };
    WGPUBuffer buf = wgpuDeviceCreateBuffer(gpu->device, &desc);
    if (!buf) {
        fprintf(stderr, "[btrc-gpu] buffer creation failed\n");
        return NULL;
    }
    return (void*)buf;
}

void btrc_gpu_write_buffer(void* gpu_, void* buf, void* data, int size) {
    GPU_* gpu = (GPU_*)gpu_;
    reap_pending_async(gpu);
    if (!gpu || !gpu->queue || !buf || !data || size <= 0 || (size & 3) != 0 ||
        (unsigned long long)size > wgpuBufferGetSize((WGPUBuffer)buf)) {
        return;
    }
    wgpuQueueWriteBuffer(gpu->queue, (WGPUBuffer)buf, 0, data, (size_t)size);
}

static void on_buffer_map(WGPUMapAsyncStatus status,
                          WGPUStringView message,
                          void* ud1, void* ud2) {
    (void)message; (void)ud2;
    btrc_gpu_async_complete((BtrcGPUAsync*)ud1, (int)status, NULL);
}

bool btrc_gpu_read_buffer_checked(void* gpu_, void* buf_, void* dst, int size) {
    GPU_* gpu = (GPU_*)gpu_;
    WGPUBuffer src_buf = (WGPUBuffer)buf_;
    reap_pending_async(gpu);
    if (!gpu || !gpu->device || !gpu->queue || !gpu->instance || !src_buf ||
        !dst || size <= 0 || (size & 3) != 0 ||
        (unsigned long long)size > wgpuBufferGetSize(src_buf)) {
        return false;
    }

    /* Create a staging buffer for readback */
    WGPUBufferDescriptor staging_desc = {
        .size  = (unsigned long long)size,
        .usage = WGPUBufferUsage_CopyDst | WGPUBufferUsage_MapRead,
    };
    WGPUBuffer staging = wgpuDeviceCreateBuffer(gpu->device, &staging_desc);
    if (!staging) { return false; }

    /* Copy source → staging */
    WGPUCommandEncoder enc = wgpuDeviceCreateCommandEncoder(gpu->device, NULL);
    if (!enc) {
        wgpuBufferRelease(staging);
        return false;
    }
    wgpuCommandEncoderCopyBufferToBuffer(enc, src_buf, 0, staging, 0,
                                          (unsigned long long)size);
    WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(enc, NULL);
    if (!cmd) {
        wgpuCommandEncoderRelease(enc);
        wgpuBufferRelease(staging);
        return false;
    }
    wgpuQueueSubmit(gpu->queue, 1, &cmd);
    wgpuCommandBufferRelease(cmd);
    wgpuCommandEncoderRelease(enc);

    /* Map staging buffer and poll until done */
    GPUAsyncPending_* pending = (GPUAsyncPending_*)calloc(
        1, sizeof(GPUAsyncPending_));
    if (!pending) {
        wgpuBufferRelease(staging);
        return false;
    }
    BtrcGPUAsync* async = btrc_gpu_async_create(NULL);
    if (!async) {
        free(pending);
        wgpuBufferRelease(staging);
        return false;
    }
    WGPUFuture map_future = wgpuBufferMapAsync(
        staging, WGPUMapMode_Read, 0, (size_t)size,
        (WGPUBufferMapCallbackInfo){
            .mode = BTRC_GPU_ASYNC_CALLBACK_MODE,
            .callback = on_buffer_map,
            .userdata1 = async,
            .userdata2 = NULL,
        });
    int map_status = 0;
    BtrcGPUAsyncWaitOutcome outcome = btrc_gpu_async_wait(
        gpu->instance, map_future, async, gpu_async_timeout_ns,
        &map_status, NULL);
    if (outcome != BTRC_GPU_ASYNC_COMPLETED) {
        /* Unmap requests cancellation; releasing our buffer reference is safe
         * while the implementation completes that request internally. */
        wgpuBufferUnmap(staging);
        wgpuBufferRelease(staging);
        BtrcGPUAsyncWaitOutcome drain = btrc_gpu_async_wait(
            gpu->instance, map_future, async,
            gpu_async_cancel_drain_timeout_ns, NULL, NULL);
        if (drain == BTRC_GPU_ASYNC_COMPLETED) {
            btrc_gpu_async_release(async);
            free(pending);
        } else {
            pending->future = map_future;
            pending->async = async;
            btrc_gpu_pending_list_prepend(
                &gpu->pending_async, &pending->link);
            fprintf(stderr,
                    "[btrc-gpu] buffer map cancellation pending: wait=%d\n",
                    (int)drain);
        }
        return false;
    }
    btrc_gpu_async_release(async);
    free(pending);

    bool success = false;
    if ((WGPUMapAsyncStatus)map_status == WGPUMapAsyncStatus_Success) {
        const void* mapped = wgpuBufferGetConstMappedRange(staging, 0, (size_t)size);
        if (mapped) {
            memcpy(dst, mapped, (size_t)size);
            success = true;
        }
        wgpuBufferUnmap(staging);
    } else {
        fprintf(stderr, "[btrc-gpu] buffer map failed: status=%d\n",
                map_status);
    }
    wgpuBufferRelease(staging);
    return success;
}

void btrc_gpu_read_buffer(void* gpu, void* buf, void* dst, int size) {
    (void)btrc_gpu_read_buffer_checked(gpu, buf, dst, size);
}

void btrc_gpu_buffer_destroy(void* buf) {
    if (buf) wgpuBufferRelease((WGPUBuffer)buf);
}

/* ================================================================
 * Compute Pipeline
 * ================================================================ */

typedef struct {
    WGPUComputePipeline pipeline;
} GPUComputePipeline_;

void* btrc_gpu_create_compute_pipeline(void* gpu_, void* shader_,
                                        char* entry) {
    GPU_* gpu = (GPU_*)gpu_;
    GPUShader_* shader = (GPUShader_*)shader_;
    if (!gpu || !gpu->device || !shader || !shader->module || !entry) {
        return NULL;
    }

    WGPUComputePipelineDescriptor desc = {
        .compute = {
            .module     = shader->module,
            .entryPoint = { .data = entry, .length = strlen(entry) },
        },
    };
    WGPUComputePipeline cp = wgpuDeviceCreateComputePipeline(gpu->device, &desc);
    if (!cp) {
        fprintf(stderr, "[btrc-gpu] compute pipeline creation failed\n");
        return NULL;
    }

    GPUComputePipeline_* p = (GPUComputePipeline_*)calloc(
        1, sizeof(GPUComputePipeline_));
    if (!p) {
        wgpuComputePipelineRelease(cp);
        return NULL;
    }
    p->pipeline = cp;
    return p;
}

void btrc_gpu_compute_pipeline_destroy(void* p_) {
    GPUComputePipeline_* p = (GPUComputePipeline_*)p_;
    if (!p) return;
    if (p->pipeline) wgpuComputePipelineRelease(p->pipeline);
    free(p);
}

/* ================================================================
 * Bind Group
 * ================================================================ */

typedef struct {
    WGPUBindGroup group;
} GPUBindGroup_;

void* btrc_gpu_create_bind_group(void* gpu_, void* pipeline_,
                                  void** buffers, int count) {
    GPU_* gpu = (GPU_*)gpu_;
    GPUComputePipeline_* pipeline = (GPUComputePipeline_*)pipeline_;
    if (!gpu || !gpu->device || !pipeline || !pipeline->pipeline ||
        !buffers || count <= 0) {
        return NULL;
    }

    /* Get bind group layout from pipeline */
    WGPUBindGroupLayout layout =
        wgpuComputePipelineGetBindGroupLayout(pipeline->pipeline, 0);
    if (!layout) { return NULL; }

    /* Build entries */
    WGPUBindGroupEntry* entries = (WGPUBindGroupEntry*)calloc(
        (size_t)count, sizeof(WGPUBindGroupEntry));
    if (!entries) {
        wgpuBindGroupLayoutRelease(layout);
        return NULL;
    }
    for (int i = 0; i < count; i++) {
        WGPUBuffer buf = (WGPUBuffer)buffers[i];
        if (!buf) {
            free(entries);
            wgpuBindGroupLayoutRelease(layout);
            return NULL;
        }
        entries[i] = (WGPUBindGroupEntry){
            .binding = (uint32_t)i,
            .buffer  = buf,
            .offset  = 0,
            .size    = wgpuBufferGetSize(buf),
        };
    }

    WGPUBindGroupDescriptor desc = {
        .layout     = layout,
        .entryCount = (size_t)count,
        .entries    = entries,
    };
    WGPUBindGroup bg = wgpuDeviceCreateBindGroup(gpu->device, &desc);
    free(entries);
    wgpuBindGroupLayoutRelease(layout);

    if (!bg) {
        fprintf(stderr, "[btrc-gpu] bind group creation failed\n");
        return NULL;
    }

    GPUBindGroup_* g = (GPUBindGroup_*)calloc(1, sizeof(GPUBindGroup_));
    if (!g) {
        wgpuBindGroupRelease(bg);
        return NULL;
    }
    g->group = bg;
    return g;
}

void btrc_gpu_bind_group_destroy(void* bg_) {
    GPUBindGroup_* bg = (GPUBindGroup_*)bg_;
    if (!bg) return;
    if (bg->group) wgpuBindGroupRelease(bg->group);
    free(bg);
}

/* ================================================================
 * Dispatch
 * ================================================================ */

bool btrc_gpu_dispatch(void* gpu_, void* pipeline_, void* bg_,
                       int workgroups_x) {
    GPU_* gpu = (GPU_*)gpu_;
    GPUComputePipeline_* pipeline = (GPUComputePipeline_*)pipeline_;
    GPUBindGroup_* bg = (GPUBindGroup_*)bg_;
    if (!gpu || !gpu->device || !gpu->queue || !pipeline ||
        !pipeline->pipeline || !bg || !bg->group || workgroups_x <= 0) {
        return false;
    }

    WGPUCommandEncoder enc = wgpuDeviceCreateCommandEncoder(gpu->device, NULL);
    if (!enc) { return false; }
    WGPUComputePassEncoder pass = wgpuCommandEncoderBeginComputePass(enc, NULL);
    if (!pass) {
        wgpuCommandEncoderRelease(enc);
        return false;
    }

    wgpuComputePassEncoderSetPipeline(pass, pipeline->pipeline);
    wgpuComputePassEncoderSetBindGroup(pass, 0, bg->group, 0, NULL);
    wgpuComputePassEncoderDispatchWorkgroups(
        pass, (uint32_t)workgroups_x, 1, 1);

    wgpuComputePassEncoderEnd(pass);
    wgpuComputePassEncoderRelease(pass);

    WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(enc, NULL);
    if (!cmd) {
        wgpuCommandEncoderRelease(enc);
        return false;
    }
    wgpuQueueSubmit(gpu->queue, 1, &cmd);
    wgpuCommandBufferRelease(cmd);
    wgpuCommandEncoderRelease(enc);
    return true;
}

/* ================================================================
 * Uniform buffer helpers (for rendering with bound data)
 * ================================================================ */

typedef struct {
    WGPUBuffer buffer;
    float*     data;         /* CPU shadow copy */
    int        count;
    size_t     aligned_size; /* byte size rounded up to 16 */
} GPUUniform_;

void* btrc_gpu_create_uniform(void* gpu_, int float_count) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu || !gpu->device || float_count <= 0 ||
        (size_t)float_count > (SIZE_MAX - 15u) / sizeof(float)) {
        return NULL;
    }
    GPUUniform_* u = (GPUUniform_*)calloc(1, sizeof(GPUUniform_));
    if (!u) { return NULL; }
    u->count = float_count;
    size_t data_size = (size_t)float_count * sizeof(float);
    u->aligned_size = (data_size + 15u) & ~(size_t)15u;
    u->data = (float*)calloc(u->aligned_size, 1);
    if (!u->data) {
        free(u);
        return NULL;
    }

    WGPUBufferDescriptor desc = {
        .size            = (unsigned long long)u->aligned_size,
        .usage           = WGPUBufferUsage_Uniform | WGPUBufferUsage_CopyDst,
        .mappedAtCreation = false,
    };
    u->buffer = wgpuDeviceCreateBuffer(gpu->device, &desc);
    if (!u->buffer) {
        fprintf(stderr, "[btrc-gpu] uniform buffer creation failed\n");
        free(u->data);
        free(u);
        return NULL;
    }
    return u;
}

void btrc_gpu_set_uniform(void* uniform_, int index, float value) {
    GPUUniform_* u = (GPUUniform_*)uniform_;
    if (u && index >= 0 && index < u->count) {
        u->data[index] = value;
    }
}

void btrc_gpu_upload_uniform(void* gpu_, void* uniform_) {
    GPU_* gpu = (GPU_*)gpu_;
    GPUUniform_* u = (GPUUniform_*)uniform_;
    if (!gpu || !gpu->queue || !u || !u->buffer || !u->data) { return; }
    wgpuQueueWriteBuffer(gpu->queue, u->buffer, 0,
                          u->data, (size_t)u->aligned_size);
}

bool btrc_gpu_draw_uniform(void* gpu_, void* pipeline_, int vertex_count,
                           void* uniform_) {
    GPU_* gpu = (GPU_*)gpu_;
    GPURenderPipeline_* pipeline = (GPURenderPipeline_*)pipeline_;
    GPUUniform_* u = (GPUUniform_*)uniform_;
    if (!gpu || !gpu->queue || !gpu->device || !gpu->pass || !pipeline ||
        !pipeline->pipeline || !u || !u->buffer || !u->data ||
        vertex_count <= 0) {
        return false;
    }

    /* Upload CPU shadow → GPU buffer */
    wgpuQueueWriteBuffer(gpu->queue, u->buffer, 0,
                          u->data, (size_t)u->aligned_size);

    /* Get bind group layout from auto-layout render pipeline */
    WGPUBindGroupLayout layout =
        wgpuRenderPipelineGetBindGroupLayout(pipeline->pipeline, 0);
    if (!layout) { return false; }

    WGPUBindGroupEntry entry = {
        .binding = 0,
        .buffer  = u->buffer,
        .offset  = 0,
        .size    = (unsigned long long)u->aligned_size,
    };
    WGPUBindGroupDescriptor bg_desc = {
        .layout     = layout,
        .entryCount = 1,
        .entries    = &entry,
    };
    WGPUBindGroup bg = wgpuDeviceCreateBindGroup(gpu->device, &bg_desc);
    if (!bg) {
        wgpuBindGroupLayoutRelease(layout);
        return false;
    }

    /* Draw */
    wgpuRenderPassEncoderSetPipeline(gpu->pass, pipeline->pipeline);
    wgpuRenderPassEncoderSetBindGroup(gpu->pass, 0, bg, 0, NULL);
    wgpuRenderPassEncoderDraw(gpu->pass, (uint32_t)vertex_count, 1, 0, 0);

    /* Cleanup temporaries */
    wgpuBindGroupRelease(bg);
    wgpuBindGroupLayoutRelease(layout);
    return true;
}

void btrc_gpu_uniform_destroy(void* uniform_) {
    GPUUniform_* u = (GPUUniform_*)uniform_;
    if (!u) return;
    if (u->buffer) wgpuBufferRelease(u->buffer);
    free(u->data);
    free(u);
}

/* ================================================================
 * Opaque BTRC render-resource identities
 * ================================================================ */

static unsigned long long register_render_resource(
        GPU_* owner, int kind, void* resource,
        unsigned long long* owner_receipt_out) {
    if (!owner || !resource || !owner_receipt_out) { return 0; }
    *owner_receipt_out = 0;
    GPURenderResource_* entry =
        (GPURenderResource_*)calloc(1, sizeof(GPURenderResource_));
    if (!entry) { return 0; }
    unsigned long long id = next_render_resource_id++;
    if (id == 0) { id = next_render_resource_id++; }
    entry->id = id;
    unsigned long long receipt = next_render_resource_id++;
    if (receipt == 0) { receipt = next_render_resource_id++; }
    entry->owner_receipt = receipt;
    entry->kind = kind;
    entry->owner = owner;
    entry->resource = resource;
    entry->next = render_resources;
    render_resources = entry;
    *owner_receipt_out = receipt;
    return id;
}

static GPURenderResource_* find_render_resource(
        unsigned long long id, GPU_* owner, int kind) {
    GPURenderResource_* entry = render_resources;
    while (entry) {
        if (entry->id == id && entry->owner == owner && entry->kind == kind) {
            return entry;
        }
        entry = entry->next;
    }
    return NULL;
}

static void destroy_render_resource_value(GPURenderResource_* entry) {
    if (!entry) { return; }
    switch (entry->kind) {
        case GPU_RENDER_RESOURCE_SHADER:
            btrc_gpu_shader_destroy(entry->resource);
            break;
        case GPU_RENDER_RESOURCE_PIPELINE:
            btrc_gpu_pipeline_destroy(entry->resource);
            break;
        case GPU_RENDER_RESOURCE_UNIFORM:
            btrc_gpu_uniform_destroy(entry->resource);
            break;
        case GPU_RENDER_RESOURCE_NATIVE_UI:
            btrc_gpu_native_ui_destroy(entry->resource);
            break;
        default:
            break;
    }
}

static int close_render_resource(
        unsigned long long id,
        unsigned long long owner_receipt,
        int kind) {
    GPURenderResource_** link = &render_resources;
    while (*link) {
        GPURenderResource_* entry = *link;
        if (entry->id == id && entry->kind == kind) {
            if (owner_receipt == 0 ||
                entry->owner_receipt != owner_receipt) {
                return BTRC_GPU_CLOSE_INVALID;
            }
            if (!render_owner_pointer_locked(entry->owner)) {
                return entry->owner && entry->owner == active_render_gpu &&
                        entry->owner->app_surface
                    ? BTRC_GPU_CLOSE_NOT_OWNER_THREAD
                    : BTRC_GPU_CLOSE_INVALID;
            }
            *link = entry->next;
            destroy_render_resource_value(entry);
            free(entry);
            return BTRC_GPU_CLOSE_CLOSED;
        }
        link = &entry->next;
    }
    return BTRC_GPU_CLOSE_INVALID;
}

static void destroy_render_resources(GPU_* gpu) {
    GPURenderResource_** link = &render_resources;
    while (*link) {
        GPURenderResource_* entry = *link;
        if (entry->owner == gpu) {
            *link = entry->next;
            destroy_render_resource_value(entry);
            free(entry);
        } else {
            link = &entry->next;
        }
    }
}

static void drain_gpu_finalizers_locked(void) {
    GPU_* gpu = active_render_gpu;
    if (!render_owner_pointer_locked(gpu)) { return; }

    GPURenderResource_** link = &render_resources;
    while (*link) {
        GPURenderResource_* entry = *link;
        if (entry->owner == gpu && entry->finalize_pending) {
            *link = entry->next;
            destroy_render_resource_value(entry);
            free(entry);
        } else {
            link = &entry->next;
        }
    }

    if (gpu->finalize_pending) {
        active_render_gpu = NULL;
        active_render_gpu_id = 0;
        destroy_gpu_unchecked(gpu);
    }
}

static void btrc_gpu_drain_owner_finalizers(void) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    render_lock_leave();
}

static void finalize_render_resource(
        unsigned long long id,
        unsigned long long owner_receipt,
        int kind) {
    render_lock_enter();
    GPURenderResource_* entry = render_resources;
    while (entry && (entry->id != id || entry->kind != kind)) {
        entry = entry->next;
    }
    if (entry && owner_receipt != 0 &&
        entry->owner_receipt == owner_receipt) {
        entry->finalize_pending = true;
    }
    render_lock_leave();
    btrc_gpu_drain_owner_finalizers();
}

int std_gpu_shader_create(
        unsigned long long gpu_id,
        char* wgsl_source,
        unsigned long long* shader_out,
        unsigned long long* owner_receipt_out) {
    if (!shader_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *shader_out = 0;
    *owner_receipt_out = 0;
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        return status;
    }
    if (!wgsl_source || wgsl_source[0] == '\0') {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    void* shader = btrc_gpu_create_shader(gpu, wgsl_source);
    if (!shader) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_CREATION_FAILED;
    }
    unsigned long long id = register_render_resource(
        gpu, GPU_RENDER_RESOURCE_SHADER, shader, owner_receipt_out);
    if (id == 0) {
        btrc_gpu_shader_destroy(shader);
        render_lock_leave();
        return BTRC_GPU_RESOURCE_OUT_OF_MEMORY;
    }
    *shader_out = id;
    render_lock_leave();
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_shader_destroy(
        unsigned long long shader,
        unsigned long long owner_receipt) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    int result = close_render_resource(
        shader, owner_receipt, GPU_RENDER_RESOURCE_SHADER);
    render_lock_leave();
    return result;
}

void std_gpu_shader_finalize(
        unsigned long long shader,
        unsigned long long owner_receipt) {
    finalize_render_resource(
        shader, owner_receipt, GPU_RENDER_RESOURCE_SHADER);
}

int std_gpu_pipeline_create(
        unsigned long long gpu_id, unsigned long long shader_id,
        char* vertex_entry, char* fragment_entry,
        unsigned long long* pipeline_out,
        unsigned long long* owner_receipt_out) {
    if (!pipeline_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *pipeline_out = 0;
    *owner_receipt_out = 0;
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        return status;
    }
    if (!vertex_entry || vertex_entry[0] == '\0' ||
        !fragment_entry || fragment_entry[0] == '\0') {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    GPURenderResource_* shader = find_render_resource(
        shader_id, gpu, GPU_RENDER_RESOURCE_SHADER);
    if (!shader) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    void* pipeline = btrc_gpu_create_render_pipeline(
        gpu, shader->resource, vertex_entry, fragment_entry);
    if (!pipeline) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_CREATION_FAILED;
    }
    unsigned long long id = register_render_resource(
        gpu, GPU_RENDER_RESOURCE_PIPELINE, pipeline, owner_receipt_out);
    if (id == 0) {
        btrc_gpu_pipeline_destroy(pipeline);
        render_lock_leave();
        return BTRC_GPU_RESOURCE_OUT_OF_MEMORY;
    }
    *pipeline_out = id;
    render_lock_leave();
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_pipeline_destroy(
        unsigned long long pipeline,
        unsigned long long owner_receipt) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    int result = close_render_resource(
        pipeline, owner_receipt, GPU_RENDER_RESOURCE_PIPELINE);
    render_lock_leave();
    return result;
}

void std_gpu_pipeline_finalize(
        unsigned long long pipeline,
        unsigned long long owner_receipt) {
    finalize_render_resource(
        pipeline, owner_receipt, GPU_RENDER_RESOURCE_PIPELINE);
}

int std_gpu_uniform_create(
        unsigned long long gpu_id,
        int float_count,
        unsigned long long* uniform_out,
        unsigned long long* owner_receipt_out) {
    if (!uniform_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *uniform_out = 0;
    *owner_receipt_out = 0;
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        return status;
    }
    if (float_count <= 0 ||
        (size_t)float_count > (SIZE_MAX - 15u) / sizeof(float)) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    void* uniform = btrc_gpu_create_uniform(gpu, float_count);
    if (!uniform) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_CREATION_FAILED;
    }
    unsigned long long id = register_render_resource(
        gpu, GPU_RENDER_RESOURCE_UNIFORM, uniform, owner_receipt_out);
    if (id == 0) {
        btrc_gpu_uniform_destroy(uniform);
        render_lock_leave();
        return BTRC_GPU_RESOURCE_OUT_OF_MEMORY;
    }
    *uniform_out = id;
    render_lock_leave();
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_uniform_set(unsigned long long uniform_id, int index, float value) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPURenderResource_* uniform = render_resources;
    while (uniform && (uniform->id != uniform_id ||
           uniform->kind != GPU_RENDER_RESOURCE_UNIFORM)) {
        uniform = uniform->next;
    }
    if (!uniform) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    if (!uniform->owner || uniform->owner != active_render_gpu ||
        !uniform->owner->app_surface) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    if (!std_app_surface_glfw(uniform->owner->app_surface)) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD;
    }
    if (device_is_lost(uniform->owner)) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_DEVICE_LOST;
    }
    GPUUniform_* native_uniform = (GPUUniform_*)uniform->resource;
    if (!native_uniform) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    if (index < 0 || index >= native_uniform->count) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    btrc_gpu_set_uniform(uniform->resource, index, value);
    render_lock_leave();
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_uniform_destroy(
        unsigned long long uniform,
        unsigned long long owner_receipt) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    int result = close_render_resource(
        uniform, owner_receipt, GPU_RENDER_RESOURCE_UNIFORM);
    render_lock_leave();
    return result;
}

void std_gpu_uniform_finalize(
        unsigned long long uniform,
        unsigned long long owner_receipt) {
    finalize_render_resource(
        uniform, owner_receipt, GPU_RENDER_RESOURCE_UNIFORM);
}

int std_gpu_draw(unsigned long long gpu_id, unsigned long long pipeline_id, int vertex_count) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        switch (status) {
            case BTRC_GPU_RESOURCE_INVALID_GPU:
                return BTRC_GPU_DRAW_INVALID_GPU;
            case BTRC_GPU_RESOURCE_NOT_OWNER_THREAD:
                return BTRC_GPU_DRAW_NOT_OWNER_THREAD;
            case BTRC_GPU_RESOURCE_DEVICE_LOST:
                return BTRC_GPU_DRAW_DEVICE_LOST;
            default:
                return BTRC_GPU_DRAW_BACKEND_FAILURE;
        }
    }
    if (vertex_count <= 0) {
        render_lock_leave();
        return BTRC_GPU_DRAW_INVALID_DESCRIPTOR;
    }
    GPURenderResource_* pipeline = find_render_resource(
        pipeline_id, gpu, GPU_RENDER_RESOURCE_PIPELINE);
    if (!pipeline) {
        render_lock_leave();
        return BTRC_GPU_DRAW_INVALID_RESOURCE;
    }
    if (!gpu->pass) {
        render_lock_leave();
        return BTRC_GPU_DRAW_NO_ACTIVE_FRAME;
    }
    btrc_gpu_draw(gpu, pipeline->resource, vertex_count);
    render_lock_leave();
    return BTRC_GPU_DRAW_RECORDED;
}

int std_gpu_draw_uniform(
        unsigned long long gpu_id, unsigned long long pipeline_id,
        int vertex_count, unsigned long long uniform_id) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        switch (status) {
            case BTRC_GPU_RESOURCE_INVALID_GPU:
                return BTRC_GPU_DRAW_INVALID_GPU;
            case BTRC_GPU_RESOURCE_NOT_OWNER_THREAD:
                return BTRC_GPU_DRAW_NOT_OWNER_THREAD;
            case BTRC_GPU_RESOURCE_DEVICE_LOST:
                return BTRC_GPU_DRAW_DEVICE_LOST;
            default:
                return BTRC_GPU_DRAW_BACKEND_FAILURE;
        }
    }
    if (vertex_count <= 0) {
        render_lock_leave();
        return BTRC_GPU_DRAW_INVALID_DESCRIPTOR;
    }
    GPURenderResource_* pipeline = find_render_resource(
        pipeline_id, gpu, GPU_RENDER_RESOURCE_PIPELINE);
    GPURenderResource_* uniform = find_render_resource(
        uniform_id, gpu, GPU_RENDER_RESOURCE_UNIFORM);
    if (!pipeline || !uniform) {
        render_lock_leave();
        return BTRC_GPU_DRAW_INVALID_RESOURCE;
    }
    if (!gpu->pass) {
        render_lock_leave();
        return BTRC_GPU_DRAW_NO_ACTIVE_FRAME;
    }
    int result = btrc_gpu_draw_uniform(
        gpu, pipeline->resource, vertex_count, uniform->resource);
    render_lock_leave();
    return result
        ? BTRC_GPU_DRAW_RECORDED : BTRC_GPU_DRAW_BACKEND_FAILURE;
}

/* ================================================================
 * Native UI display-list resource
 * ================================================================ */

static int native_ui_resource_locked(
        unsigned long long compositor_id,
        GPU_** gpu_out,
        GPURenderResource_** resource_out) {
    if (gpu_out) { *gpu_out = NULL; }
    if (resource_out) { *resource_out = NULL; }
    if (!gpu_out || !resource_out || compositor_id == 0) {
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    GPURenderResource_* resource = render_resources;
    while (resource && (resource->id != compositor_id ||
           resource->kind != GPU_RENDER_RESOURCE_NATIVE_UI)) {
        resource = resource->next;
    }
    if (!resource || !resource->owner ||
        resource->owner != active_render_gpu ||
        !resource->owner->app_surface) {
        return BTRC_GPU_RESOURCE_INVALID_RESOURCE;
    }
    if (!std_app_surface_glfw(resource->owner->app_surface)) {
        return BTRC_GPU_RESOURCE_NOT_OWNER_THREAD;
    }
    if (device_is_lost(resource->owner)) {
        return BTRC_GPU_RESOURCE_DEVICE_LOST;
    }
    *gpu_out = resource->owner;
    *resource_out = resource;
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_native_ui_create(
        unsigned long long gpu_id,
        unsigned long long* compositor_out,
        unsigned long long* owner_receipt_out) {
    if (!compositor_out || !owner_receipt_out) {
        return BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    *compositor_out = 0;
    *owner_receipt_out = 0;
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        return status;
    }
    void* compositor = btrc_gpu_native_ui_create(
        gpu->device, gpu->queue, gpu->surface_format);
    if (!compositor) {
        render_lock_leave();
        return BTRC_GPU_RESOURCE_CREATION_FAILED;
    }
    unsigned long long identity = register_render_resource(
        gpu, GPU_RENDER_RESOURCE_NATIVE_UI,
        compositor, owner_receipt_out);
    if (identity == 0) {
        btrc_gpu_native_ui_destroy(compositor);
        render_lock_leave();
        return BTRC_GPU_RESOURCE_OUT_OF_MEMORY;
    }
    *compositor_out = identity;
    render_lock_leave();
    return BTRC_GPU_RESOURCE_READY;
}

int std_gpu_native_ui_begin(
        unsigned long long compositor_id,
        int logical_width,
        int logical_height) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    GPURenderResource_* resource = NULL;
    int status = native_ui_resource_locked(
        compositor_id, &gpu, &resource);
    (void)gpu;
    if (status == BTRC_GPU_RESOURCE_READY &&
        !btrc_gpu_native_ui_begin(
            resource->resource, logical_width, logical_height)) {
        status = BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    render_lock_leave();
    return status;
}

int std_gpu_native_ui_add_rect(
        unsigned long long compositor_id,
        float x,
        float y,
        float width,
        float height,
        float red,
        float green,
        float blue,
        float alpha,
        float radius) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    GPURenderResource_* resource = NULL;
    int status = native_ui_resource_locked(
        compositor_id, &gpu, &resource);
    (void)gpu;
    if (status == BTRC_GPU_RESOURCE_READY &&
        !btrc_gpu_native_ui_add_rect(
            resource->resource, x, y, width, height,
            red, green, blue, alpha, radius)) {
        status = BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    render_lock_leave();
    return status;
}

int std_gpu_native_ui_add_glyph(
        unsigned long long compositor_id,
        float x,
        float y,
        float width,
        float height,
        float red,
        float green,
        float blue,
        float alpha,
        unsigned long long glyph_bits) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    GPURenderResource_* resource = NULL;
    int status = native_ui_resource_locked(
        compositor_id, &gpu, &resource);
    (void)gpu;
    if (status == BTRC_GPU_RESOURCE_READY &&
        !btrc_gpu_native_ui_add_glyph(
            resource->resource, x, y, width, height,
            red, green, blue, alpha, (uint64_t)glyph_bits)) {
        status = BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    render_lock_leave();
    return status;
}

int std_gpu_native_ui_add_image(
        unsigned long long compositor_id,
        char* identity,
        unsigned char* rgba,
        int source_width,
        int source_height,
        unsigned long long source_revision,
        float x,
        float y,
        float width,
        float height) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    GPURenderResource_* resource = NULL;
    int status = native_ui_resource_locked(
        compositor_id, &gpu, &resource);
    (void)gpu;
    if (status == BTRC_GPU_RESOURCE_READY &&
        !btrc_gpu_native_ui_add_image(
            resource->resource, identity, rgba,
            source_width, source_height, (uint64_t)source_revision,
            x, y, width, height)) {
        status = BTRC_GPU_RESOURCE_INVALID_DESCRIPTOR;
    }
    render_lock_leave();
    return status;
}

int std_gpu_native_ui_draw(
        unsigned long long gpu_id,
        unsigned long long compositor_id) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    int gpu_status = render_gpu_resource_status_locked(gpu_id, &gpu);
    if (gpu_status != BTRC_GPU_RESOURCE_READY) {
        render_lock_leave();
        switch (gpu_status) {
            case BTRC_GPU_RESOURCE_INVALID_GPU:
                return BTRC_GPU_DRAW_INVALID_GPU;
            case BTRC_GPU_RESOURCE_NOT_OWNER_THREAD:
                return BTRC_GPU_DRAW_NOT_OWNER_THREAD;
            case BTRC_GPU_RESOURCE_DEVICE_LOST:
                return BTRC_GPU_DRAW_DEVICE_LOST;
            default:
                return BTRC_GPU_DRAW_BACKEND_FAILURE;
        }
    }
    GPURenderResource_* resource = find_render_resource(
        compositor_id, gpu, GPU_RENDER_RESOURCE_NATIVE_UI);
    if (!resource) {
        render_lock_leave();
        return BTRC_GPU_DRAW_INVALID_RESOURCE;
    }
    if (!gpu->pass) {
        render_lock_leave();
        return BTRC_GPU_DRAW_NO_ACTIVE_FRAME;
    }
    bool recorded = btrc_gpu_native_ui_draw(
        resource->resource, gpu->pass);
    render_lock_leave();
    return recorded
        ? BTRC_GPU_DRAW_RECORDED : BTRC_GPU_DRAW_BACKEND_FAILURE;
}

int std_gpu_native_ui_destroy(
        unsigned long long compositor,
        unsigned long long owner_receipt) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    int result = close_render_resource(
        compositor, owner_receipt, GPU_RENDER_RESOURCE_NATIVE_UI);
    render_lock_leave();
    return result;
}

void std_gpu_native_ui_finalize(
        unsigned long long compositor,
        unsigned long long owner_receipt) {
    finalize_render_resource(
        compositor, owner_receipt, GPU_RENDER_RESOURCE_NATIVE_UI);
}

int std_gpu_native_ui_command_count(unsigned long long compositor_id) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    GPURenderResource_* resource = NULL;
    int status = native_ui_resource_locked(
        compositor_id, &gpu, &resource);
    (void)gpu;
    int result = status == BTRC_GPU_RESOURCE_READY
        ? btrc_gpu_native_ui_command_count(resource->resource) : -1;
    render_lock_leave();
    return result;
}

int std_gpu_native_ui_image_count(unsigned long long compositor_id) {
    render_lock_enter();
    drain_gpu_finalizers_locked();
    GPU_* gpu = NULL;
    GPURenderResource_* resource = NULL;
    int status = native_ui_resource_locked(
        compositor_id, &gpu, &resource);
    (void)gpu;
    int result = status == BTRC_GPU_RESOURCE_READY
        ? btrc_gpu_native_ui_image_count(resource->resource) : -1;
    render_lock_leave();
    return result;
}
