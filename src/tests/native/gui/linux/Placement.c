#include "Placement.h"
#include "GUI/Shim/ShimControls.h"
#include <webgpu.h>

static int placed;
static int passes;
static int frames;

/* Link-only observation: every call is delegated unchanged. */
void __real_btrcShimWindowBeginPlacement(BtrcShimWindow *window);
void __wrap_btrcShimWindowBeginPlacement(BtrcShimWindow *window) {
    placed = 0;
    passes++;
    __real_btrcShimWindowBeginPlacement(window);
}

void __real_btrcShimWindowPlace(BtrcShimWindow *window, BtrcShimControl *control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
void __wrap_btrcShimWindowPlace(BtrcShimWindow *window, BtrcShimControl *control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
    placed++;
    __real_btrcShimWindowPlace(window, control, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result == WGPUStatus_Success) { frames++; }
    return result;
}

void __real_btrcShimWindowShowPicture(BtrcShimWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight);
void __wrap_btrcShimWindowShowPicture(BtrcShimWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight) {
    __real_btrcShimWindowShowPicture(window, pixels, pixelWidth, pixelHeight);
    frames++;
}

int placementPlaced(void) { return placed; }
int placementPasses(void) { return passes; }
int placementFrames(void) { return frames; }
