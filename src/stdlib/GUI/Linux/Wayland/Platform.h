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

BtrcShimWindow *btrcWaylandPlatformWindows(void);
void btrcWaylandSceneClose(BtrcShimWindow *window);
int btrcWaylandSceneAdvance(int timeout);
bool btrcWaylandScenePresent(BtrcShimWindow *window);
bool btrcWaylandSceneInput(BtrcWaylandDisplay *display, const BtrcShimEvent *event, bool *handled);
#endif
