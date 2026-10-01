/*
 * Compiler-only WebGPU compute runtime.
 *
 * Generated @gpu dispatch helpers still require this C ABI for headless
 * compute, synchronous readback, and CPU-fallback probing. Portable GUI/GPU
 * rendering uses typed native SDK imports and does not link this runtime.
 * Links against WebGPU and pthreads on POSIX (SRWLOCK on Windows), never GLFW.
 */

#include "btrc_gpu_compute_internal.h"
#include "btrc_gpu_async.h"
#include "btrc_gpu_compute_singleton.h"
#include "btrc_gpu_pending_list.h"
#include <webgpu.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct GPU_ {
    WGPUInstance instance;
    WGPUAdapter adapter;
    WGPUDevice device;
    WGPUQueue queue;
    BtrcGPUPendingList pending_async;
    BtrcGPUAsync* device_lost_async;
    WGPUFuture device_lost_future;
    struct GPU_* compute_next;
} GPU_;

typedef struct {
    WGPUShaderModule module;
} GPUShader_;

typedef struct {
    BtrcGPUPendingLink link;
    WGPUFuture future;
    BtrcGPUAsync* async;
} GPUAsyncPending_;

static GPU_* compute_gpus = NULL;
static _Atomic(void*) btrc_compute_singleton = NULL;

#ifdef _WIN32
static SRWLOCK compute_lock = SRWLOCK_INIT;
#else
static pthread_mutex_t compute_lock = PTHREAD_MUTEX_INITIALIZER;
#endif

static void compute_lock_enter(void) {
#ifdef _WIN32
    AcquireSRWLockExclusive(&compute_lock);
#else
    (void)pthread_mutex_lock(&compute_lock);
#endif
}

static void compute_lock_leave(void) {
#ifdef _WIN32
    ReleaseSRWLockExclusive(&compute_lock);
#else
    (void)pthread_mutex_unlock(&compute_lock);
#endif
}

static void destroy_gpu_unchecked(GPU_* gpu);
static bool device_is_lost(GPU_* gpu);

/* Native WebGPU requests are asynchronous even though the btrc wrapper exposes
 * synchronous construction/readback.  Bound every such bridge so a wedged
 * driver cannot hang the process forever. */
static const unsigned long long gpu_async_timeout_ns = UINT64_C(30000000000);
static const unsigned long long gpu_async_cancel_drain_timeout_ns = UINT64_C(100000000);

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

static void on_uncaptured_error(
        WGPUDevice const* device,
        WGPUErrorType type,
        WGPUStringView message,
        void* ud1,
        void* ud2) {
    (void)device;
    (void)message;
    (void)ud1;
    (void)ud2;
    fprintf(stderr, "[btrc-gpu] uncaptured WebGPU error: type=%d\n", (int)type);
}

static void on_error_scope(
        WGPUPopErrorScopeStatus status,
        WGPUErrorType type,
        WGPUStringView message,
        void* ud1,
        void* ud2) {
    (void)message;
    (void)ud2;
    int result = status == WGPUPopErrorScopeStatus_Success
        ? (int)type : 0;
    btrc_gpu_async_complete((BtrcGPUAsync*)ud1, result, NULL);
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
    configured.uncapturedErrorCallbackInfo =
        (WGPUUncapturedErrorCallbackInfo){
            .callback = on_uncaptured_error,
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
    compute_lock_enter();
    GPU_** link = &compute_gpus;
    while (*link && *link != gpu) { link = &(*link)->compute_next; }
    if (!*link) {
        compute_lock_leave();
        return;
    }
    *link = gpu->compute_next;
    gpu->compute_next = NULL;
    compute_lock_leave();
    /* Only registered compute candidates reach the hosted deallocator. */
    destroy_gpu_unchecked(gpu);
}

static void destroy_gpu_unchecked(GPU_* gpu) {
    if (!gpu) { return; }
    reap_pending_async(gpu);
    if (gpu->queue)    wgpuQueueRelease(gpu->queue);
    if (gpu->device) {
        wgpuDeviceDestroy(gpu->device);
        (void)device_is_lost(gpu);
        wgpuDeviceRelease(gpu->device);
    }
    if (gpu->adapter)  wgpuAdapterRelease(gpu->adapter);
    if (gpu->instance) {
        wgpuInstanceRelease(gpu->instance);
        gpu->instance = NULL;
    }
    btrc_gpu_async_release(gpu->device_lost_async);
    release_pending_async_callers(gpu);
    if (!btrc_gpu_pending_list_destroy(&gpu->pending_async)) {
        fprintf(stderr, "[btrc-gpu] pending-list mutex destroy failed\n");
    }
    free(gpu);
}

/* ================================================================
 * Shader
 * ================================================================ */

void* btrc_gpu_create_shader(void* gpu_, char* wgsl_source) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu || !gpu->device || !wgsl_source) { return NULL; }
    BtrcGPUAsync* validation = btrc_gpu_async_create(NULL);
    if (!validation) { return NULL; }
    wgpuDevicePushErrorScope(gpu->device, WGPUErrorFilter_Validation);
    WGPUShaderSourceWGSL wgsl = {
        .chain = { .sType = WGPUSType_ShaderSourceWGSL },
        .code  = { .data = wgsl_source, .length = strlen(wgsl_source) },
    };
    WGPUShaderModuleDescriptor desc = {
        .nextInChain = (WGPUChainedStruct*)&wgsl,
    };
    WGPUShaderModule mod = wgpuDeviceCreateShaderModule(gpu->device, &desc);
    WGPUFuture validation_future = wgpuDevicePopErrorScope(
        gpu->device,
        (WGPUPopErrorScopeCallbackInfo){
            .mode = BTRC_GPU_ASYNC_CALLBACK_MODE,
            .callback = on_error_scope,
            .userdata1 = validation,
        });
    int validation_result = 0;
    BtrcGPUAsyncWaitOutcome validation_wait = btrc_gpu_async_wait(
        gpu->instance, validation_future, validation,
        gpu_async_timeout_ns, &validation_result, NULL);
    btrc_gpu_async_release(validation);
    if (validation_wait != BTRC_GPU_ASYNC_COMPLETED ||
            validation_result != (int)WGPUErrorType_NoError || !mod) {
        if (mod) { wgpuShaderModuleRelease(mod); }
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
 * Headless compute (no window/surface needed)
 * ================================================================ */

void* btrc_gpu_init_compute(void) {
    GPU_* gpu = (GPU_*)calloc(1, sizeof(GPU_));
    if (!gpu) { return NULL; }
    if (!btrc_gpu_pending_list_init(&gpu->pending_async)) {
        free(gpu);
        return NULL;
    }

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
    compute_lock_enter();
    gpu->compute_next = compute_gpus;
    compute_gpus = gpu;
    compute_lock_leave();
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
