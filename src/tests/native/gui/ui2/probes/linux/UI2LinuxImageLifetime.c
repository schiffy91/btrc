#include "UI2LinuxImageLifetime.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <webgpu.h>

/* Actual executable-origin SDK claims, not backend-private allocation counts.
 * The original publication race runs outside this per-cycle census. */
typedef enum { WINDOW, TEXTURE, TEXTURE_VIEW, BIND_GROUP, CLASS_COUNT } Kind;
static const char *const names[CLASS_COUNT] = {"window", "texture", "texture_view", "bind_group"};
typedef struct { Kind kind; void *handle; unsigned int refs; } Claim;
typedef struct { unsigned int created, retained, released, live; } Counts;
static Claim claims[4096];
static Counts counts[CLASS_COUNT];
static atomic_flag ledger_lock = ATOMIC_FLAG_INIT;
static atomic_int workers;
static int current_cycle;
static unsigned int image_textures;
static bool active;
static void lock(void) { while (atomic_flag_test_and_set_explicit(&ledger_lock, memory_order_acquire)) {} }
static void unlock(void) { atomic_flag_clear_explicit(&ledger_lock, memory_order_release); }
static void acquire(Kind kind, void *handle, bool retain) {
    assert(handle); lock();
    if (!active) { unlock(); return; }
    size_t vacant = 4096, found = 4096;
    for (size_t i = 0; i < 4096; i++) {
        if (claims[i].refs && claims[i].kind == kind && claims[i].handle == handle) { found = i; break; }
        if (!claims[i].refs) vacant = i;
    }
    if (retain) assert(found < 4096);
    if (found == 4096) { assert(vacant < 4096); found = vacant; claims[found] = (Claim){kind, handle, 0}; }
    claims[found].refs++; counts[kind].live++;
    if (retain) counts[kind].retained++; else counts[kind].created++;
    unlock();
}
static void retire(Kind kind, void *handle) {
    assert(handle); lock();
    if (!active) { unlock(); return; }
    size_t found = 4096;
    for (size_t i = 0; i < 4096; i++) {
        if (claims[i].refs && claims[i].kind == kind && claims[i].handle == handle) { found = i; break; }
    }
    if (found == 4096) { fprintf(stderr, "image unowned release %s %p\n", names[kind], handle); abort(); }
    assert(counts[kind].live); claims[found].refs--; counts[kind].live--; counts[kind].released++;
    unlock();
}
void ui2ImageBegin(int cycle) {
    assert(SDL_IsMainThread()); lock(); assert(!active && cycle == current_cycle + 1);
    for (int i = 0; i < CLASS_COUNT; i++) { assert(counts[i].live == 0); counts[i] = (Counts){0}; }
    current_cycle = cycle; image_textures = 0; atomic_store(&workers, 0); active = true; unlock();
}
void ui2ImageWorker(void) { assert(!SDL_IsMainThread()); atomic_fetch_add(&workers, 1); }
void ui2ImageEnd(int cycle) {
    assert(SDL_IsMainThread()); lock();
    assert(active && current_cycle == cycle && atomic_load(&workers) == 2 && image_textures == 2);
    printf("UI2_IMAGE_LIFETIME {\"cycle\":%d,\"order\":%d,\"explicit_original_close\":%s,\"workers\":%d,\"image_textures\":%u,\"resources\":[", cycle, (cycle - 1) % 4, (cycle - 1) / 4 % 2 == 1 ? "true" : "false", atomic_load(&workers), image_textures);
    for (int i = 0; i < CLASS_COUNT; i++) {
        Counts row = counts[i];
        printf("%s{\"class\":\"%s\",\"created\":%u,\"retained\":%u,\"released\":%u,\"live\":%u}", i ? "," : "", names[i], row.created, row.retained, row.released, row.live);
        assert(row.created > 0 && row.live == 0 && row.created + row.retained == row.released);
    }
    printf("]}\n"); fflush(stdout); active = false; unlock();
}
#define CREATE(kind, type, name, parameters, arguments) \
    extern type __real_##name parameters; \
    type __wrap_##name parameters { type result = __real_##name arguments; if (result) acquire(kind, result, false); return result; }
#define REFERENCE(kind, type, stem) \
    extern void __real_##stem##AddRef(type value); \
    extern void __real_##stem##Release(type value); \
    void __wrap_##stem##AddRef(type value) { __real_##stem##AddRef(value); acquire(kind, value, true); } \
    void __wrap_##stem##Release(type value) { retire(kind, value); __real_##stem##Release(value); }
CREATE(WINDOW, SDL_Window *, SDL_CreateWindow, (const char *title, int width, int height, SDL_WindowFlags flags), (title, width, height, flags))
extern void __real_SDL_DestroyWindow(SDL_Window *window);
void __wrap_SDL_DestroyWindow(SDL_Window *window) { retire(WINDOW, window); __real_SDL_DestroyWindow(window); }
extern WGPUTexture __real_wgpuDeviceCreateTexture(WGPUDevice device, const WGPUTextureDescriptor *descriptor);
WGPUTexture __wrap_wgpuDeviceCreateTexture(WGPUDevice device, const WGPUTextureDescriptor *descriptor) {
    WGPUTexture result = __real_wgpuDeviceCreateTexture(device, descriptor);
    if (result) {
        acquire(TEXTURE, result, false); lock();
        if (active && descriptor->size.width == 2 && descriptor->size.height == 2) image_textures++;
        unlock();
    }
    return result;
}
CREATE(TEXTURE_VIEW, WGPUTextureView, wgpuTextureCreateView, (WGPUTexture texture, const WGPUTextureViewDescriptor *descriptor), (texture, descriptor))
CREATE(BIND_GROUP, WGPUBindGroup, wgpuDeviceCreateBindGroup, (WGPUDevice device, const WGPUBindGroupDescriptor *descriptor), (device, descriptor))
REFERENCE(TEXTURE, WGPUTexture, wgpuTexture)
REFERENCE(TEXTURE_VIEW, WGPUTextureView, wgpuTextureView)
REFERENCE(BIND_GROUP, WGPUBindGroup, wgpuBindGroup)
extern void __real_wgpuSurfaceGetCurrentTexture(WGPUSurface surface, WGPUSurfaceTexture *texture);
void __wrap_wgpuSurfaceGetCurrentTexture(WGPUSurface surface, WGPUSurfaceTexture *texture) {
    __real_wgpuSurfaceGetCurrentTexture(surface, texture);
    if (texture->texture) acquire(TEXTURE, texture->texture, false);
}
