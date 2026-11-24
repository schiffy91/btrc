#ifndef BTRC_WAYLAND_PLATFORM_H
#define BTRC_WAYLAND_PLATFORM_H
#include "Window.h"
#include "../../Shim/ShimControls.h"

typedef struct {
    double x, y, width, height;
} BtrcWaylandRect;

typedef struct {
    BtrcShimControl *control;
    BtrcWaylandRect frame;
    BtrcWaylandRect clip;
} BtrcWaylandPlacement;

typedef struct {
    BtrcWaylandPlacement *items;
    size_t count;
    size_t capacity;
} BtrcWaylandPlacements;

struct BtrcShimWindow {
    BtrcWaylandWindow *native;
    BtrcWaylandGPUView *gpu;
    BtrcShimWindow *next;
    BtrcWaylandPlacements visible;
    BtrcWaylandPlacements pending;
    bool placementFailed;
    bool sceneDirty;
    unsigned char *background;
    int backgroundWidth;
    int backgroundHeight;
    long long animationAt;
    struct BtrcWaylandSelect *menu;
    BtrcShimControl *tooltipTarget;
    long long tooltipAt;
    double tooltipX, tooltipY;
    BtrcShimControl *focused;
    BtrcShimControl *hovered;
    BtrcShimControl *pressed;
    unsigned pressKey;
    BtrcShimControl *rangeDrag;
    double rangeAnchor;
};

/* The software painter samples immutable, premultiplied DRM XRGB/ARGB planes
 * directly from their producer's mapping. Replacing a plane releases its owner. */
enum BtrcWaylandPixelLayout { BTRC_WL_RGBA, BTRC_WL_DRM_XRGB, BTRC_WL_DRM_ARGB };
void btrcWaylandPictureStorage(BtrcShimControl *picture, unsigned char *pixels, size_t stride,
                               int width, int height, enum BtrcWaylandPixelLayout layout,
                               void *owner, void (*release)(void *));
BtrcShimWindow *btrcWaylandPlatformWindows(void);
bool btrcWaylandSceneDark(void);
void btrcWaylandSceneClose(BtrcShimWindow *window);
int btrcWaylandSceneAdvance(int timeout);
bool btrcWaylandScenePresent(BtrcShimWindow *window);
struct BtrcEditContext;
bool btrcWaylandSceneEditContext(BtrcWaylandWindow *window, struct BtrcEditContext *context);
bool btrcWaylandSceneDeleteAround(BtrcWaylandWindow *window, unsigned before, unsigned after);
bool btrcWaylandSceneInput(BtrcWaylandDisplay *display, const BtrcShimEvent *event, bool *handled);
#endif
