/* Platform-specific GLFW to WebGPU surface bridging. */

#include "btrc_gpu_surface.h"

#ifdef __APPLE__
WGPUSurface btrc_gpu_create_surface_macos(
    WGPUInstance instance, GLFWwindow* window);
#elif defined(__linux__)
#define GLFW_EXPOSE_NATIVE_X11
#define GLFW_EXPOSE_NATIVE_WAYLAND
#include <GLFW/glfw3native.h>
#elif defined(_WIN32)
#define GLFW_EXPOSE_NATIVE_WIN32
#include <GLFW/glfw3native.h>
#endif

WGPUSurface btrc_gpu_create_surface(
        WGPUInstance instance, GLFWwindow* window) {
    if (!instance || !window) { return NULL; }
#ifdef __APPLE__
    return btrc_gpu_create_surface_macos(instance, window);
#elif defined(__linux__)
    WGPUSurfaceDescriptor descriptor = { 0 };
    WGPUSurfaceSourceXlibWindow x11_source = { 0 };
    WGPUSurfaceSourceWaylandSurface wayland_source = { 0 };
    int platform = glfwGetPlatform();
    if (platform == GLFW_PLATFORM_WAYLAND) {
        wayland_source = (WGPUSurfaceSourceWaylandSurface){
            .chain = { .sType = WGPUSType_SurfaceSourceWaylandSurface },
            .display = glfwGetWaylandDisplay(),
            .surface = glfwGetWaylandWindow(window),
        };
        if (!wayland_source.display || !wayland_source.surface) { return NULL; }
        descriptor.nextInChain = (WGPUChainedStruct*)&wayland_source;
    } else if (platform == GLFW_PLATFORM_X11) {
        x11_source = (WGPUSurfaceSourceXlibWindow){
            .chain = { .sType = WGPUSType_SurfaceSourceXlibWindow },
            .display = glfwGetX11Display(),
            .window = (uint64_t)glfwGetX11Window(window),
        };
        if (!x11_source.display || !x11_source.window) { return NULL; }
        descriptor.nextInChain = (WGPUChainedStruct*)&x11_source;
    } else {
        return NULL;
    }
    return wgpuInstanceCreateSurface(instance, &descriptor);
#elif defined(_WIN32)
    WGPUSurfaceSourceWindowsHWND source = {
        .chain = { .sType = WGPUSType_SurfaceSourceWindowsHWND },
        .hinstance = (void*)GetModuleHandleW(NULL),
        .hwnd = (void*)glfwGetWin32Window(window),
    };
    if (!source.hinstance || !source.hwnd) { return NULL; }
#else
    /* Compute remains portable; rendering needs a platform surface source. */
    return NULL;
#endif

#ifdef _WIN32
    WGPUSurfaceDescriptor descriptor = {
        .nextInChain = (WGPUChainedStruct*)&source,
    };
    return wgpuInstanceCreateSurface(instance, &descriptor);
#endif
}
