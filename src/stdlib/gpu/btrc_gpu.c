/*
 * btrc GPU Runtime — WebGPU implementation
 *
 * On macOS: compile with  clang -x objective-c  (or rename to .m)
 * On Linux: compile with  gcc
 *
 * Links against: libwgpu_native (or Dawn), GLFW, platform frameworks
 */

#include "btrc_gpu.h"
#include <webgpu.h>
#include <GLFW/glfw3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- macOS: Metal surface via Objective-C ---- */
#ifdef __APPLE__
#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3native.h>
#import <QuartzCore/CAMetalLayer.h>

static WGPUSurface create_surface_macos(WGPUInstance instance, GLFWwindow* window) {
    NSWindow* ns_window = glfwGetCocoaWindow(window);
    NSView* view = [ns_window contentView];
    [view setWantsLayer:YES];
    CAMetalLayer* layer = [CAMetalLayer layer];
    [view setLayer:layer];

    WGPUSurfaceSourceMetalLayer src = {
        .chain = { .sType = WGPUSType_SurfaceSourceMetalLayer },
        .layer = layer,
    };
    WGPUSurfaceDescriptor desc = {
        .nextInChain = (WGPUChainedStruct*)&src,
    };
    return wgpuInstanceCreateSurface(instance, &desc);
}
#endif

/* ---- Linux: X11 surface ---- */
#ifdef __linux__
#define GLFW_EXPOSE_NATIVE_X11
#include <GLFW/glfw3native.h>

static WGPUSurface create_surface_linux(WGPUInstance instance, GLFWwindow* window) {
    Display* x11_display = glfwGetX11Display();
    Window x11_window = glfwGetX11Window(window);

    WGPUSurfaceSourceXlibWindow src = {
        .chain = { .sType = WGPUSType_SurfaceSourceXlibWindow },
        .display = x11_display,
        .window = (uint64_t)x11_window,
    };
    WGPUSurfaceDescriptor desc = {
        .nextInChain = (WGPUChainedStruct*)&src,
    };
    return wgpuInstanceCreateSurface(instance, &desc);
}
#endif

/* ================================================================
 * Internal structs
 * ================================================================ */

typedef struct {
    GLFWwindow* glfw;
    int         width;
    int         height;
} GPUWindow_;

typedef struct {
    WGPUInstance      instance;
    WGPUSurface       surface;
    WGPUAdapter       adapter;
    WGPUDevice        device;
    WGPUQueue         queue;
    WGPUTextureFormat surface_format;
    /* Per-frame state */
    WGPUCommandEncoder     encoder;
    WGPURenderPassEncoder  pass;
    WGPUTexture            frame_texture;
    WGPUTextureView        frame_view;
    GPUWindow_*            window;
} GPU_;

typedef struct {
    WGPUShaderModule module;
} GPUShader_;

typedef struct {
    WGPURenderPipeline pipeline;
} GPURenderPipeline_;

/* ================================================================
 * Async request helpers
 * ================================================================ */

static void on_adapter(WGPURequestAdapterStatus status, WGPUAdapter adapter,
                       WGPUStringView message, void* ud1, void* ud2) {
    (void)message; (void)ud2;
    GPU_* gpu = (GPU_*)ud1;
    if (status == WGPURequestAdapterStatus_Success) {
        gpu->adapter = adapter;
    } else {
        fprintf(stderr, "[btrc-gpu] adapter request failed: status=%d\n", status);
    }
}

static void on_device(WGPURequestDeviceStatus status, WGPUDevice device,
                      WGPUStringView message, void* ud1, void* ud2) {
    (void)message; (void)ud2;
    GPU_* gpu = (GPU_*)ud1;
    if (status == WGPURequestDeviceStatus_Success) {
        gpu->device = device;
    } else {
        fprintf(stderr, "[btrc-gpu] device request failed: status=%d\n", status);
    }
}

/* ================================================================
 * Window
 * ================================================================ */

void* btrc_gpu_window_create(char* title, int width, int height) {
    if (!glfwInit()) {
        fprintf(stderr, "[btrc-gpu] glfwInit failed\n");
        exit(1);
    }
    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);

    GLFWwindow* glfw = glfwCreateWindow(width, height, title, NULL, NULL);
    if (!glfw) {
        fprintf(stderr, "[btrc-gpu] glfwCreateWindow failed\n");
        glfwTerminate();
        exit(1);
    }

    GPUWindow_* win = (GPUWindow_*)calloc(1, sizeof(GPUWindow_));
    win->glfw   = glfw;
    win->width  = width;
    win->height = height;
    return win;
}

bool btrc_gpu_window_is_open(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    return !glfwWindowShouldClose(win->glfw);
}

void btrc_gpu_window_poll(void* win_) {
    (void)win_;
    glfwPollEvents();
}

int btrc_gpu_window_width(void* win_)  { return ((GPUWindow_*)win_)->width; }
int btrc_gpu_window_height(void* win_) { return ((GPUWindow_*)win_)->height; }

void btrc_gpu_window_destroy(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    if (!win) return;
    if (win->glfw) glfwDestroyWindow(win->glfw);
    glfwTerminate();
    free(win);
}

/* ================================================================
 * GPU init
 * ================================================================ */

void* btrc_gpu_init(void* win_) {
    GPUWindow_* win = (GPUWindow_*)win_;
    GPU_* gpu = (GPU_*)calloc(1, sizeof(GPU_));
    gpu->window = win;

    /* Instance */
    WGPUInstanceDescriptor inst_desc = { 0 };
    gpu->instance = wgpuCreateInstance(&inst_desc);
    if (!gpu->instance) {
        fprintf(stderr, "[btrc-gpu] wgpuCreateInstance failed\n");
        exit(1);
    }

    /* Surface */
#ifdef __APPLE__
    gpu->surface = create_surface_macos(gpu->instance, win->glfw);
#elif defined(__linux__)
    gpu->surface = create_surface_linux(gpu->instance, win->glfw);
#else
    #error "Unsupported platform — add surface creation for your OS"
#endif
    if (!gpu->surface) {
        fprintf(stderr, "[btrc-gpu] surface creation failed\n");
        exit(1);
    }

    /* Adapter (AllowSpontaneous: callback fires during the request call) */
    WGPURequestAdapterOptions adapter_opts = {
        .compatibleSurface = gpu->surface,
        .featureLevel = WGPUFeatureLevel_Core,
    };
    wgpuInstanceRequestAdapter(
        gpu->instance, &adapter_opts,
        (WGPURequestAdapterCallbackInfo){
            .mode = WGPUCallbackMode_AllowSpontaneous,
            .callback = on_adapter,
            .userdata1 = gpu,
        });
    if (!gpu->adapter) {
        fprintf(stderr, "[btrc-gpu] no suitable GPU adapter found\n");
        exit(1);
    }

    /* Device (AllowSpontaneous: callback fires during the request call) */
    wgpuAdapterRequestDevice(
        gpu->adapter, NULL,
        (WGPURequestDeviceCallbackInfo){
            .mode = WGPUCallbackMode_AllowSpontaneous,
            .callback = on_device,
            .userdata1 = gpu,
        });
    if (!gpu->device) {
        fprintf(stderr, "[btrc-gpu] device request failed\n");
        exit(1);
    }

    /* Queue */
    gpu->queue = wgpuDeviceGetQueue(gpu->device);

    /* Surface format + configure */
    WGPUSurfaceCapabilities caps = { 0 };
    wgpuSurfaceGetCapabilities(gpu->surface, gpu->adapter, &caps);
    gpu->surface_format = caps.formats[0];

    WGPUSurfaceConfiguration config = {
        .device      = gpu->device,
        .usage       = WGPUTextureUsage_RenderAttachment,
        .format      = gpu->surface_format,
        .presentMode = WGPUPresentMode_Fifo,
        .alphaMode   = caps.alphaModes[0],
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
    if (gpu->queue)    wgpuQueueRelease(gpu->queue);
    if (gpu->device)   wgpuDeviceRelease(gpu->device);
    if (gpu->adapter)  wgpuAdapterRelease(gpu->adapter);
    if (gpu->surface)  wgpuSurfaceRelease(gpu->surface);
    if (gpu->instance) wgpuInstanceRelease(gpu->instance);
    free(gpu);
}

/* ================================================================
 * Shader
 * ================================================================ */

void* btrc_gpu_create_shader(void* gpu_, char* wgsl_source) {
    GPU_* gpu = (GPU_*)gpu_;
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
        exit(1);
    }

    GPUShader_* s = (GPUShader_*)calloc(1, sizeof(GPUShader_));
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
        exit(1);
    }

    GPURenderPipeline_* p = (GPURenderPipeline_*)calloc(1, sizeof(GPURenderPipeline_));
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

    /* Get current surface texture */
    WGPUSurfaceTexture st;
    wgpuSurfaceGetCurrentTexture(gpu->surface, &st);

    if (st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal &&
        st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessSuboptimal) {
        /* Reconfigure on outdated/lost */
        if (st.texture) wgpuTextureRelease(st.texture);
        int w, h;
        glfwGetWindowSize(gpu->window->glfw, &w, &h);
        if (w > 0 && h > 0) {
            gpu->window->width  = w;
            gpu->window->height = h;
            WGPUSurfaceConfiguration config = {
                .device      = gpu->device,
                .usage       = WGPUTextureUsage_RenderAttachment,
                .format      = gpu->surface_format,
                .presentMode = WGPUPresentMode_Fifo,
                .alphaMode   = WGPUCompositeAlphaMode_Auto,
                .width       = (uint32_t)w,
                .height      = (uint32_t)h,
            };
            wgpuSurfaceConfigure(gpu->surface, &config);
        }
        return false;
    }

    gpu->frame_texture = st.texture;
    gpu->frame_view = wgpuTextureCreateView(st.texture, NULL);

    /* Command encoder */
    gpu->encoder = wgpuDeviceCreateCommandEncoder(gpu->device, NULL);

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
    return true;
}

void btrc_gpu_draw(void* gpu_, void* pipeline_, int vertex_count) {
    GPU_* gpu = (GPU_*)gpu_;
    GPURenderPipeline_* pipeline = (GPURenderPipeline_*)pipeline_;
    wgpuRenderPassEncoderSetPipeline(gpu->pass, pipeline->pipeline);
    wgpuRenderPassEncoderDraw(gpu->pass, (uint32_t)vertex_count, 1, 0, 0);
}

void btrc_gpu_end_frame(void* gpu_) {
    GPU_* gpu = (GPU_*)gpu_;

    wgpuRenderPassEncoderEnd(gpu->pass);
    wgpuRenderPassEncoderRelease(gpu->pass);
    gpu->pass = NULL;

    WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(gpu->encoder, NULL);
    wgpuQueueSubmit(gpu->queue, 1, &cmd);
    wgpuSurfacePresent(gpu->surface);

    wgpuCommandBufferRelease(cmd);
    wgpuCommandEncoderRelease(gpu->encoder);
    wgpuTextureViewRelease(gpu->frame_view);
    wgpuTextureRelease(gpu->frame_texture);

    gpu->encoder       = NULL;
    gpu->frame_view    = NULL;
    gpu->frame_texture = NULL;
}
