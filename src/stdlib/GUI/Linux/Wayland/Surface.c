/* Match ShimWindow's full-window painter. A transparent CPU overlay draws
 * its placed controls, and holes reveal the driver's surface below it. */
#include "Platform.h"
#include "../../Shim/ShimSurface.h"

WGPUInstance btrcShimCreateInstance(void) { return wgpuCreateInstance(NULL); }

WGPUSurface btrcShimWindowCreateSurface(BtrcShimWindow *window, WGPUInstance instance) {
    if (!window || !instance) { return NULL; }
    BtrcWaylandGPUView *child = window->gpu;
    if (!child) {
        child = btrcWaylandWindowAttachGPU(window->native, 0, 0);
        if (!child) { return NULL; }
        if (!btrcWaylandGPUViewPlaceBelowParent(child)) { btrcWaylandGPUViewDestroy(child); return NULL; }
    }
    WGPUSurfaceSourceWaylandSurface wayland = {
        .chain = {.sType = WGPUSType_SurfaceSourceWaylandSurface},
        .display = btrcWaylandGPUViewDisplay(child),
        .surface = btrcWaylandGPUViewSurface(child),
    };
    WGPUSurfaceDescriptor desc = {.nextInChain = &wayland.chain};
    WGPUSurface surface = wgpuInstanceCreateSurface(instance, &desc);
    if (!window->gpu) {
        if (!surface) { btrcWaylandGPUViewDestroy(child); return NULL; }
        window->gpu = child;
        if (!btrcWaylandScenePresent(window)) {
            wgpuSurfaceRelease(surface);
            window->gpu = NULL;
            btrcWaylandGPUViewDestroy(child);
            return NULL;
        }
    }
    return surface;
}
