/*
 * btrc GPU Runtime — WebGPU implementation
 *
 * This file is strict C11 on every platform. The small macOS Metal/Cocoa
 * surface bridge lives in btrc_gpu_surface_macos.m.
 *
 * Links against: libwgpu_native (or Dawn), GLFW, platform frameworks
 */

#include "btrc_gpu.h"
#include "btrc_gpu_async.h"
#include "btrc_gpu_compute_singleton.h"
#include "btrc_gpu_pending_list.h"
#include "btrc_gpu_surface.h"
#include <webgpu.h>
#include <GLFW/glfw3.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ================================================================
 * Internal structs
 * ================================================================ */

typedef struct {
    GLFWwindow* glfw;
    int         width;
    int         height;
    unsigned int ref_count;
} GPUWindow_;

typedef struct GPUAsyncPending_ GPUAsyncPending_;

typedef struct {
    WGPUInstance      instance;
    WGPUSurface       surface;
    WGPUAdapter       adapter;
    WGPUDevice        device;
    WGPUQueue         queue;
    WGPUTextureFormat surface_format;
    WGPUCompositeAlphaMode surface_alpha_mode;
    /* Per-frame state */
    WGPUCommandEncoder     encoder;
    WGPURenderPassEncoder  pass;
    WGPUTexture            frame_texture;
    WGPUTextureView        frame_view;
    GPUWindow_*            window;
    BtrcGPUPendingList     pending_async;
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

/* GLFW is process-global and may also be used by the GUI backend. Individual
 * windows are destroyed here; global teardown is intentionally left to exit. */
static bool glfw_initialized = false;

/* Native WebGPU requests are asynchronous even though the btrc wrapper exposes
 * synchronous construction/readback.  Bound every such bridge so a wedged
 * driver cannot hang the process forever. */
static const uint64_t gpu_async_timeout_ns = UINT64_C(30000000000);
static const uint64_t gpu_async_cancel_drain_timeout_ns = UINT64_C(100000000);

static bool acquire_glfw(void) {
    if (!glfw_initialized) {
        if (!glfwInit()) { return false; }
        glfw_initialized = true;
    }
    return true;
}

static bool retain_window(GPUWindow_* window) {
    if (!window || window->ref_count == UINT_MAX) { return false; }
    window->ref_count++;
    return true;
}

static void release_window(GPUWindow_* window) {
    if (!window || window->ref_count == 0) { return; }
    window->ref_count--;
    if (window->ref_count != 0) { return; }
    if (window->glfw) { glfwDestroyWindow(window->glfw); }
    free(window);
}

static void refresh_window_size(GPUWindow_* window) {
    if (!window || !window->glfw) { return; }
    glfwGetFramebufferSize(window->glfw, &window->width, &window->height);
}

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
    WGPUFuture future = wgpuAdapterRequestDevice(
        gpu->adapter, descriptor,
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
        fprintf(stderr,
                "[btrc-gpu] device request failed: wait=%d status=%d\n",
                (int)outcome, status);
        return false;
    }
    gpu->device = (WGPUDevice)result;
    return true;
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
 * Window
 * ================================================================ */

void* btrc_gpu_window_create(char* title, int width, int height) {
    if (width <= 0 || height <= 0) { return NULL; }
    if (!acquire_glfw()) {
        fprintf(stderr, "[btrc-gpu] glfwInit failed\n");
        return NULL;
    }
    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);

    GLFWwindow* glfw = glfwCreateWindow(
        width, height, title ? title : "btrc", NULL, NULL);
    if (!glfw) {
        fprintf(stderr, "[btrc-gpu] glfwCreateWindow failed\n");
        return NULL;
    }

    GPUWindow_* win = (GPUWindow_*)calloc(1, sizeof(GPUWindow_));
    if (!win) {
        glfwDestroyWindow(glfw);
        return NULL;
    }
    win->glfw   = glfw;
    win->ref_count = 1;
    glfwGetFramebufferSize(glfw, &win->width, &win->height);
    if (win->width <= 0 || win->height <= 0) {
        win->width = width;
        win->height = height;
    }
    return win;
}

bool btrc_gpu_window_is_open(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    return win && win->glfw && !glfwWindowShouldClose(win->glfw);
}

void btrc_gpu_window_poll(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    if (!win || !win->glfw) { return; }
    glfwPollEvents();
    refresh_window_size(win);
}

int btrc_gpu_window_width(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    refresh_window_size(win);
    return win ? win->width : 0;
}
int btrc_gpu_window_height(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    refresh_window_size(win);
    return win ? win->height : 0;
}

void btrc_gpu_window_destroy(void* win_) {
    release_window((GPUWindow_*)win_);
}

bool btrc_gpu_window_key_pressed(void* win_, int key) {
    GPUWindow_* win = (GPUWindow_*)win_;
    return win && win->glfw && glfwGetKey(win->glfw, key) == GLFW_PRESS;
}

float btrc_gpu_get_time(void) {
    return (float)glfwGetTime();
}

/* ================================================================
 * GPU init
 * ================================================================ */

void* btrc_gpu_init(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    if (!win || !win->glfw) { return NULL; }
    GPU_* gpu = (GPU_*)calloc(1, sizeof(GPU_));
    if (!gpu) { return NULL; }
    btrc_gpu_pending_list_init(&gpu->pending_async);
    if (!retain_window(win)) {
        free(gpu);
        return NULL;
    }
    gpu->window = win;

    /* Instance */
    gpu->instance = create_gpu_instance();
    if (!gpu->instance) {
        fprintf(stderr, "[btrc-gpu] wgpuCreateInstance failed\n");
        btrc_gpu_destroy(gpu);
        return NULL;
    }

    gpu->surface = btrc_gpu_create_surface(gpu->instance, win->glfw);
    if (!gpu->surface) {
        fprintf(stderr, "[btrc-gpu] surface creation failed\n");
        btrc_gpu_destroy(gpu);
        return NULL;
    }

    /* Conforming backends wait on this exact future; wgpu-native serializes
     * event pumping and publishes callback state atomically. */
    WGPURequestAdapterOptions adapter_opts = {
        .compatibleSurface = gpu->surface,
        .featureLevel = WGPUFeatureLevel_Core,
    };
    if (!request_adapter(gpu, &adapter_opts)) {
        fprintf(stderr, "[btrc-gpu] no suitable GPU adapter found\n");
        btrc_gpu_destroy(gpu);
        return NULL;
    }

    /* Likewise, keep the device callback on this thread before returning. */
    if (!request_device(gpu, NULL)) {
        fprintf(stderr, "[btrc-gpu] device request failed\n");
        btrc_gpu_destroy(gpu);
        return NULL;
    }

    /* Queue */
    gpu->queue = wgpuDeviceGetQueue(gpu->device);
    if (!gpu->queue) {
        btrc_gpu_destroy(gpu);
        return NULL;
    }

    /* Surface format + configure */
    WGPUSurfaceCapabilities caps = { 0 };
    if (wgpuSurfaceGetCapabilities(gpu->surface, gpu->adapter, &caps) !=
            WGPUStatus_Success ||
        caps.formatCount == 0 || !caps.formats ||
        caps.alphaModeCount == 0 || !caps.alphaModes) {
        wgpuSurfaceCapabilitiesFreeMembers(caps);
        btrc_gpu_destroy(gpu);
        return NULL;
    }
    gpu->surface_format = caps.formats[0];
    gpu->surface_alpha_mode = caps.alphaModes[0];

    WGPUSurfaceConfiguration config = {
        .device      = gpu->device,
        .usage       = WGPUTextureUsage_RenderAttachment,
        .format      = gpu->surface_format,
        .presentMode = WGPUPresentMode_Fifo,
        .alphaMode   = gpu->surface_alpha_mode,
        .width       = (uint32_t)win->width,
        .height      = (uint32_t)win->height,
    };
    wgpuSurfaceConfigure(gpu->surface, &config);
    wgpuSurfaceCapabilitiesFreeMembers(caps);

    return gpu;
}

void btrc_gpu_destroy(void* gpu_) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu) return;
    reap_pending_async(gpu);
    discard_frame(gpu);
    if (gpu->queue)    wgpuQueueRelease(gpu->queue);
    if (gpu->device)   wgpuDeviceRelease(gpu->device);
    if (gpu->adapter)  wgpuAdapterRelease(gpu->adapter);
    if (gpu->surface)  wgpuSurfaceRelease(gpu->surface);
    if (gpu->instance) {
        wgpuInstanceRelease(gpu->instance);
        gpu->instance = NULL;
    }
    release_pending_async_callers(gpu);
    release_window(gpu->window);
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

bool btrc_gpu_begin_frame(void* gpu_, float r, float g, float b, float a) {
    GPU_* gpu = (GPU_*)gpu_;
    reap_pending_async(gpu);
    if (!gpu || !gpu->surface || !gpu->device || !gpu->window ||
        !gpu->window->glfw || gpu->pass || gpu->encoder || gpu->frame_texture ||
        gpu->frame_view) {
        return false;
    }

    /* Get current surface texture */
    WGPUSurfaceTexture st = { 0 };
    wgpuSurfaceGetCurrentTexture(gpu->surface, &st);

    if (st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal &&
        st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessSuboptimal) {
        /* Reconfigure on outdated/lost */
        if (st.texture) wgpuTextureRelease(st.texture);
        int w, h;
        glfwGetFramebufferSize(gpu->window->glfw, &w, &h);
        if (w > 0 && h > 0) {
            gpu->window->width  = w;
            gpu->window->height = h;
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
        return false;
    }
    if (!st.texture) { return false; }

    gpu->frame_texture = st.texture;
    gpu->frame_view = wgpuTextureCreateView(st.texture, NULL);
    if (!gpu->frame_view) {
        discard_frame(gpu);
        return false;
    }

    /* Command encoder */
    gpu->encoder = wgpuDeviceCreateCommandEncoder(gpu->device, NULL);
    if (!gpu->encoder) {
        discard_frame(gpu);
        return false;
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
        return false;
    }
    return true;
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

void btrc_gpu_end_frame(void* gpu_) {
    GPU_* gpu = (GPU_*)gpu_;
    if (!gpu || !gpu->pass || !gpu->encoder || !gpu->frame_view ||
        !gpu->frame_texture) {
        discard_frame(gpu);
        return;
    }

    wgpuRenderPassEncoderEnd(gpu->pass);
    wgpuRenderPassEncoderRelease(gpu->pass);
    gpu->pass = NULL;

    WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(gpu->encoder, NULL);
    if (cmd) {
        wgpuQueueSubmit(gpu->queue, 1, &cmd);
        wgpuSurfacePresent(gpu->surface);
        wgpuCommandBufferRelease(cmd);
    }

    wgpuCommandEncoderRelease(gpu->encoder);
    wgpuTextureViewRelease(gpu->frame_view);
    wgpuTextureRelease(gpu->frame_texture);

    gpu->encoder       = NULL;
    gpu->frame_view    = NULL;
    gpu->frame_texture = NULL;
}

/* ================================================================
 * Headless compute (no window/surface needed)
 * ================================================================ */

void* btrc_gpu_init_compute(void) {
    GPU_* gpu = (GPU_*)calloc(1, sizeof(GPU_));
    if (!gpu) { return NULL; }
    btrc_gpu_pending_list_init(&gpu->pending_async);
    gpu->window = NULL;
    gpu->surface = NULL;

    gpu->instance = create_gpu_instance();
    if (!gpu->instance) {
        /* Non-fatal: callers probe via btrc_gpu_available() and fall back to CPU. */
        free(gpu);
        return NULL;
    }

    WGPURequestAdapterOptions adapter_opts = {
        .featureLevel = WGPUFeatureLevel_Core,
    };
    if (!request_adapter(gpu, &adapter_opts)) {
        btrc_gpu_destroy(gpu);
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
        btrc_gpu_destroy(gpu);
        return NULL;
    }

    gpu->queue = wgpuDeviceGetQueue(gpu->device);
    if (!gpu->queue) {
        btrc_gpu_destroy(gpu);
        return NULL;
    }
    return gpu;
}

/* Process-lifetime compute context. Device and queue handles are safe to use
 * from concurrent callers; per-dispatch buffers and pipelines remain local. */
static _Atomic(void*) btrc_compute_singleton = NULL;

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
        .size            = (uint64_t)size,
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
        (uint64_t)size > wgpuBufferGetSize((WGPUBuffer)buf)) {
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
        (uint64_t)size > wgpuBufferGetSize(src_buf)) {
        return false;
    }

    /* Create a staging buffer for readback */
    WGPUBufferDescriptor staging_desc = {
        .size  = (uint64_t)size,
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
                                          (uint64_t)size);
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
        .size            = (uint64_t)u->aligned_size,
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

void btrc_gpu_draw_uniform(void* gpu_, void* pipeline_, int vertex_count,
                            void* uniform_) {
    GPU_* gpu = (GPU_*)gpu_;
    GPURenderPipeline_* pipeline = (GPURenderPipeline_*)pipeline_;
    GPUUniform_* u = (GPUUniform_*)uniform_;
    if (!gpu || !gpu->queue || !gpu->device || !gpu->pass || !pipeline ||
        !pipeline->pipeline || !u || !u->buffer || !u->data ||
        vertex_count <= 0) {
        return;
    }

    /* Upload CPU shadow → GPU buffer */
    wgpuQueueWriteBuffer(gpu->queue, u->buffer, 0,
                          u->data, (size_t)u->aligned_size);

    /* Get bind group layout from auto-layout render pipeline */
    WGPUBindGroupLayout layout =
        wgpuRenderPipelineGetBindGroupLayout(pipeline->pipeline, 0);
    if (!layout) { return; }

    WGPUBindGroupEntry entry = {
        .binding = 0,
        .buffer  = u->buffer,
        .offset  = 0,
        .size    = (uint64_t)u->aligned_size,
    };
    WGPUBindGroupDescriptor bg_desc = {
        .layout     = layout,
        .entryCount = 1,
        .entries    = &entry,
    };
    WGPUBindGroup bg = wgpuDeviceCreateBindGroup(gpu->device, &bg_desc);
    if (!bg) {
        wgpuBindGroupLayoutRelease(layout);
        return;
    }

    /* Draw */
    wgpuRenderPassEncoderSetPipeline(gpu->pass, pipeline->pipeline);
    wgpuRenderPassEncoderSetBindGroup(gpu->pass, 0, bg, 0, NULL);
    wgpuRenderPassEncoderDraw(gpu->pass, (uint32_t)vertex_count, 1, 0, 0);

    /* Cleanup temporaries */
    wgpuBindGroupRelease(bg);
    wgpuBindGroupLayoutRelease(layout);
}

void btrc_gpu_uniform_destroy(void* uniform_) {
    GPUUniform_* u = (GPUUniform_*)uniform_;
    if (!u) return;
    if (u->buffer) wgpuBufferRelease(u->buffer);
    free(u->data);
    free(u);
}
