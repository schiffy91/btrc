#ifndef BTRC_GPU_SURFACE_H
#define BTRC_GPU_SURFACE_H

#include <GLFW/glfw3.h>
#include <webgpu.h>

WGPUSurface btrc_gpu_create_surface(
    WGPUInstance instance, GLFWwindow* window);

#endif
