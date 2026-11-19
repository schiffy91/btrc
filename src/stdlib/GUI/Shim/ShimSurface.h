#ifndef BTRC_SHIM_SURFACE_H
#define BTRC_SHIM_SURFACE_H
/* The WebGPU surface a window's drawn content is presented on. It is a
 * header of its own because it names WebGPU's types. */
#include <webgpu.h>
#include "Shim.h"

/* A surface on `instance` for the window's drawn content, or NULL when the
 * window has nothing a surface can be made on. The caller releases it
 * before the window is destroyed. */
WGPUSurface btrcShimWindowCreateSurface(BtrcShimWindow* window, WGPUInstance instance);
#endif
