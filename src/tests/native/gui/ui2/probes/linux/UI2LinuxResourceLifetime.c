#include "UI2LinuxResourceLifetime.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <webgpu.h>

/* --wrap observes executable-origin claims only. Every resource is created by
 * the real SDK; driver-internal references and allocations are not counted. */
typedef enum {
    WINDOW, CURSOR, INSTANCE, SURFACE, ADAPTER, DEVICE, QUEUE, BUFFER, TEXTURE,
    TEXTURE_VIEW, BIND_GROUP, BIND_GROUP_LAYOUT, PIPELINE_LAYOUT, RENDER_PIPELINE,
    SAMPLER, SHADER, COMMAND_ENCODER, RENDER_PASS, COMMAND_BUFFER, CLASS_COUNT
} ResourceClass;
static const char *const names[CLASS_COUNT] = {
    "window", "cursor", "instance", "surface", "adapter", "device", "queue",
    "buffer", "texture", "texture_view", "bind_group", "bind_group_layout",
    "pipeline_layout", "render_pipeline", "sampler", "shader",
    "command_encoder", "render_pass", "command_buffer"
};
typedef struct { ResourceClass kind; void *handle; unsigned int refs; } Claim;
typedef struct { unsigned int created, retained, released, live; } Counts;
static Claim claims[4096];
static Counts counts[CLASS_COUNT];
static atomic_flag ledger_lock = ATOMIC_FLAG_INIT;
static unsigned int pending_requests;
static int current_cycle;
static unsigned int text_cursors, default_cursors;
static void lock(void) { while (atomic_flag_test_and_set_explicit(&ledger_lock, memory_order_acquire)) {} }
static void unlock(void) { atomic_flag_clear_explicit(&ledger_lock, memory_order_release); }

static void acquire(ResourceClass kind, void *handle, int retain) {
    assert(handle);
    lock();
    size_t vacant = 4096;
    size_t found = 4096;
    for (size_t i = 0; i < 4096; i++) {
        if (claims[i].refs && claims[i].kind == kind && claims[i].handle == handle) { found = i; break; }
        if (!claims[i].refs) { vacant = i; }
    }
    if (retain) { assert(found < 4096); }
    if (found == 4096) { assert(vacant < 4096); found = vacant; claims[found] = (Claim){kind, handle, 0}; }
    claims[found].refs++;
    counts[kind].live++;
    if (retain) { counts[kind].retained++; } else { counts[kind].created++; }
    unlock();
}
static void retire(ResourceClass kind, void *handle) {
    assert(handle);
    lock();
    size_t found = 4096;
    for (size_t i = 0; i < 4096; i++) {
        if (claims[i].refs && claims[i].kind == kind && claims[i].handle == handle) { found = i; break; }
    }
    if (found == 4096) { fprintf(stderr, "unowned release: %s %p\n", names[kind], handle); abort(); }
    assert(counts[kind].live);
    claims[found].refs--; counts[kind].live--; counts[kind].released++;
    unlock();
}
void ui2ResourceBegin(int cycle) {
    lock();
    assert(cycle == current_cycle + 1 && pending_requests == 0);
    for (int i = 0; i < CLASS_COUNT; i++) { assert(counts[i].live == 0); counts[i] = (Counts){0}; }
    current_cycle = cycle; text_cursors = 0; default_cursors = 0;
    unlock();
}
void ui2ResourceEnd(int cycle) {
    lock();
    assert(cycle == current_cycle && pending_requests == 0);
    for (int i = 0; i < CLASS_COUNT; i++) {
        Counts row = counts[i];
        printf("UI2_RESOURCE {\"cycle\":%d,\"class\":\"%s\",\"created\":%u,\"retained\":%u,\"released\":%u,\"live\":%u}\n",
               cycle, names[i], row.created, row.retained, row.released, row.live);
        fflush(stdout);
        assert(row.created > 0 && row.live == 0 && row.created + row.retained == row.released);
    }
    assert(counts[CURSOR].created == 2 && text_cursors == 1 && default_cursors == 1);
    unlock();
}
int ui2ResourceCursorCount(int text) { lock(); int result = (int)(text ? text_cursors : default_cursors); unlock(); return result; }
void ui2ResourcePointer(unsigned int window, float x, float y) {
    SDL_Event event = {0}; event.type = SDL_EVENT_MOUSE_MOTION;
    event.motion.windowID = window; event.motion.x = x; event.motion.y = y;
    assert(SDL_PushEvent(&event));
}

#define CREATE(kind, type, name, parameters, arguments) \
    extern type __real_##name parameters; \
    type __wrap_##name parameters { type result = __real_##name arguments; if (result) { acquire(kind, result, 0); } return result; }
#define REFERENCE(kind, type, stem) \
    extern void __real_##stem##AddRef(type value); \
    extern void __real_##stem##Release(type value); \
    void __wrap_##stem##AddRef(type value) { __real_##stem##AddRef(value); acquire(kind, value, 1); } \
    void __wrap_##stem##Release(type value) { retire(kind, value); __real_##stem##Release(value); }
CREATE(WINDOW, SDL_Window *, SDL_CreateWindow, (const char *title, int width, int height, SDL_WindowFlags flags), (title, width, height, flags))
extern SDL_Cursor *__real_SDL_CreateSystemCursor(SDL_SystemCursor id);
SDL_Cursor *__wrap_SDL_CreateSystemCursor(SDL_SystemCursor id) {
    SDL_Cursor *cursor = __real_SDL_CreateSystemCursor(id);
    if (cursor) {
        acquire(CURSOR, cursor, 0);
        lock();
        assert(id == SDL_SYSTEM_CURSOR_TEXT || id == SDL_SYSTEM_CURSOR_DEFAULT);
        if (id == SDL_SYSTEM_CURSOR_TEXT) { text_cursors++; } else { default_cursors++; }
        unlock();
    }
    return cursor;
}
extern void __real_SDL_DestroyWindow(SDL_Window *window);
extern void __real_SDL_DestroyCursor(SDL_Cursor *cursor);
void __wrap_SDL_DestroyWindow(SDL_Window *window) { retire(WINDOW, window); __real_SDL_DestroyWindow(window); }
void __wrap_SDL_DestroyCursor(SDL_Cursor *cursor) { retire(CURSOR, cursor); __real_SDL_DestroyCursor(cursor); }
CREATE(INSTANCE, WGPUInstance, wgpuCreateInstance, (const WGPUInstanceDescriptor *descriptor), (descriptor))
CREATE(SURFACE, WGPUSurface, wgpuInstanceCreateSurface, (WGPUInstance instance, const WGPUSurfaceDescriptor *descriptor), (instance, descriptor))
CREATE(QUEUE, WGPUQueue, wgpuDeviceGetQueue, (WGPUDevice device), (device))
CREATE(BUFFER, WGPUBuffer, wgpuDeviceCreateBuffer, (WGPUDevice device, const WGPUBufferDescriptor *descriptor), (device, descriptor))
CREATE(TEXTURE, WGPUTexture, wgpuDeviceCreateTexture, (WGPUDevice device, const WGPUTextureDescriptor *descriptor), (device, descriptor))
CREATE(TEXTURE_VIEW, WGPUTextureView, wgpuTextureCreateView, (WGPUTexture texture, const WGPUTextureViewDescriptor *descriptor), (texture, descriptor))
CREATE(BIND_GROUP, WGPUBindGroup, wgpuDeviceCreateBindGroup, (WGPUDevice device, const WGPUBindGroupDescriptor *descriptor), (device, descriptor))
CREATE(BIND_GROUP_LAYOUT, WGPUBindGroupLayout, wgpuDeviceCreateBindGroupLayout, (WGPUDevice device, const WGPUBindGroupLayoutDescriptor *descriptor), (device, descriptor))
CREATE(PIPELINE_LAYOUT, WGPUPipelineLayout, wgpuDeviceCreatePipelineLayout, (WGPUDevice device, const WGPUPipelineLayoutDescriptor *descriptor), (device, descriptor))
CREATE(RENDER_PIPELINE, WGPURenderPipeline, wgpuDeviceCreateRenderPipeline, (WGPUDevice device, const WGPURenderPipelineDescriptor *descriptor), (device, descriptor))
CREATE(SAMPLER, WGPUSampler, wgpuDeviceCreateSampler, (WGPUDevice device, const WGPUSamplerDescriptor *descriptor), (device, descriptor))
CREATE(SHADER, WGPUShaderModule, wgpuDeviceCreateShaderModule, (WGPUDevice device, const WGPUShaderModuleDescriptor *descriptor), (device, descriptor))
CREATE(COMMAND_ENCODER, WGPUCommandEncoder, wgpuDeviceCreateCommandEncoder, (WGPUDevice device, const WGPUCommandEncoderDescriptor *descriptor), (device, descriptor))
CREATE(RENDER_PASS, WGPURenderPassEncoder, wgpuCommandEncoderBeginRenderPass, (WGPUCommandEncoder encoder, const WGPURenderPassDescriptor *descriptor), (encoder, descriptor))
CREATE(COMMAND_BUFFER, WGPUCommandBuffer, wgpuCommandEncoderFinish, (WGPUCommandEncoder encoder, const WGPUCommandBufferDescriptor *descriptor), (encoder, descriptor))
REFERENCE(INSTANCE, WGPUInstance, wgpuInstance)
REFERENCE(SURFACE, WGPUSurface, wgpuSurface)
REFERENCE(ADAPTER, WGPUAdapter, wgpuAdapter)
REFERENCE(DEVICE, WGPUDevice, wgpuDevice)
REFERENCE(QUEUE, WGPUQueue, wgpuQueue)
REFERENCE(BUFFER, WGPUBuffer, wgpuBuffer)
REFERENCE(TEXTURE, WGPUTexture, wgpuTexture)
REFERENCE(TEXTURE_VIEW, WGPUTextureView, wgpuTextureView)
REFERENCE(BIND_GROUP, WGPUBindGroup, wgpuBindGroup)
REFERENCE(BIND_GROUP_LAYOUT, WGPUBindGroupLayout, wgpuBindGroupLayout)
REFERENCE(PIPELINE_LAYOUT, WGPUPipelineLayout, wgpuPipelineLayout)
REFERENCE(RENDER_PIPELINE, WGPURenderPipeline, wgpuRenderPipeline)
REFERENCE(SAMPLER, WGPUSampler, wgpuSampler)
REFERENCE(SHADER, WGPUShaderModule, wgpuShaderModule)
REFERENCE(COMMAND_ENCODER, WGPUCommandEncoder, wgpuCommandEncoder)
REFERENCE(RENDER_PASS, WGPURenderPassEncoder, wgpuRenderPassEncoder)
REFERENCE(COMMAND_BUFFER, WGPUCommandBuffer, wgpuCommandBuffer)
extern void __real_wgpuSurfaceGetCurrentTexture(WGPUSurface surface, WGPUSurfaceTexture *texture);
void __wrap_wgpuSurfaceGetCurrentTexture(WGPUSurface surface, WGPUSurfaceTexture *texture) {
    __real_wgpuSurfaceGetCurrentTexture(surface, texture);
    if (texture->texture) { acquire(TEXTURE, texture->texture, 0); }
}

/* Each asynchronous request owns its original userdata independently; native
 * callbacks may overlap or arrive on a worker. No callback is delayed here. */
typedef struct { WGPURequestAdapterCallbackInfo delivery; } AdapterRequest;
typedef struct { WGPURequestDeviceCallbackInfo delivery; } DeviceRequest;
static void adapterReady(WGPURequestAdapterStatus status, WGPUAdapter adapter, WGPUStringView message, void *first, void *second) {
    (void)second; AdapterRequest *request = first;
    WGPURequestAdapterCallbackInfo delivery = request->delivery; free(request);
    if (adapter) { acquire(ADAPTER, adapter, 0); }
    delivery.callback(status, adapter, message, delivery.userdata1, delivery.userdata2);
    lock(); assert(pending_requests); pending_requests--; unlock();
}
static void deviceReady(WGPURequestDeviceStatus status, WGPUDevice device, WGPUStringView message, void *first, void *second) {
    (void)second; DeviceRequest *request = first;
    WGPURequestDeviceCallbackInfo delivery = request->delivery; free(request);
    if (device) { acquire(DEVICE, device, 0); }
    delivery.callback(status, device, message, delivery.userdata1, delivery.userdata2);
    lock(); assert(pending_requests); pending_requests--; unlock();
}
extern WGPUFuture __real_wgpuInstanceRequestAdapter(WGPUInstance instance, const WGPURequestAdapterOptions *options, WGPURequestAdapterCallbackInfo info);
WGPUFuture __wrap_wgpuInstanceRequestAdapter(WGPUInstance instance, const WGPURequestAdapterOptions *options, WGPURequestAdapterCallbackInfo info) {
    AdapterRequest *request = malloc(sizeof(*request)); assert(request); request->delivery = info;
    info.callback = adapterReady; info.userdata1 = request; info.userdata2 = NULL;
    lock(); pending_requests++; unlock();
    return __real_wgpuInstanceRequestAdapter(instance, options, info);
}
extern WGPUFuture __real_wgpuAdapterRequestDevice(WGPUAdapter adapter, const WGPUDeviceDescriptor *descriptor, WGPURequestDeviceCallbackInfo info);
WGPUFuture __wrap_wgpuAdapterRequestDevice(WGPUAdapter adapter, const WGPUDeviceDescriptor *descriptor, WGPURequestDeviceCallbackInfo info) {
    DeviceRequest *request = malloc(sizeof(*request)); assert(request); request->delivery = info;
    info.callback = deviceReady; info.userdata1 = request; info.userdata2 = NULL;
    lock(); pending_requests++; unlock();
    return __real_wgpuAdapterRequestDevice(adapter, descriptor, info);
}
