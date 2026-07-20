/* Objective-C bridge for creating a WebGPU surface from a GLFW Cocoa window. */

#ifndef GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_NONE
#endif
#include <webgpu.h>
#include <GLFW/glfw3.h>

#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3native.h>
#import <QuartzCore/CAMetalLayer.h>

WGPUSurface btrc_gpu_create_surface_macos(
    WGPUInstance instance, GLFWwindow* window) {
    NSWindow* ns_window = glfwGetCocoaWindow(window);
    NSView* view = [ns_window contentView];
    [view setWantsLayer:YES];
    CAMetalLayer* layer = [CAMetalLayer layer];
    [view setLayer:layer];

    WGPUSurfaceSourceMetalLayer source = {
        .chain = { .sType = WGPUSType_SurfaceSourceMetalLayer },
        .layer = layer,
    };
    WGPUSurfaceDescriptor descriptor = {
        .nextInChain = (WGPUChainedStruct*)&source,
    };
    return wgpuInstanceCreateSurface(instance, &descriptor);
}
