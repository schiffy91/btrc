#include "Placement.h"
#include "GUI/Linux/GtkControls.h"
#include <webgpu.h>

static int placed;
static int passes;
static int frames;

/* Link-only observation: every call is delegated unchanged. */
void __real_btrcGtkWindowBeginPlacement(BtrcGtkWindow *window);
void __wrap_btrcGtkWindowBeginPlacement(BtrcGtkWindow *window) {
    placed = 0;
    passes++;
    __real_btrcGtkWindowBeginPlacement(window);
}

void __real_btrcGtkWindowPlace(BtrcGtkWindow *window, BtrcGtkControl *control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
void __wrap_btrcGtkWindowPlace(BtrcGtkWindow *window, BtrcGtkControl *control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
    placed++;
    __real_btrcGtkWindowPlace(window, control, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result == WGPUStatus_Success) { frames++; }
    return result;
}

void __real_btrcGtkWindowShowPicture(BtrcGtkWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight);
void __wrap_btrcGtkWindowShowPicture(BtrcGtkWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight) {
    __real_btrcGtkWindowShowPicture(window, pixels, pixelWidth, pixelHeight);
    frames++;
}

int placementPlaced(void) { return placed; }
int placementPasses(void) { return passes; }
int placementFrames(void) { return frames; }
