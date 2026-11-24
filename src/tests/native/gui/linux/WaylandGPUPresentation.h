#ifndef BTRC_TEST_WAYLAND_GPU_PRESENTATION_H
#define BTRC_TEST_WAYLAND_GPU_PRESENTATION_H
#include <stdbool.h>
#include <webgpu.h>

bool openSoftwareWindow(void);
WGPUInstance createGPUInstance(void);
WGPUSurface attachGPUView(WGPUInstance instance);
bool waitForInput(void);
void closeSoftwareWindow(void);
#endif
