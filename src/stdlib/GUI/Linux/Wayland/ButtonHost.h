#ifndef BTRC_WAYLAND_BUTTON_HOST_H
#define BTRC_WAYLAND_BUTTON_HOST_H
#include "Platform.h"

typedef struct BtrcWaylandButton BtrcWaylandButton;

typedef struct {
    unsigned char *rgba;
    int width, height;
    double scale;
    BtrcWaylandRect frame, clip;
    bool dark, enabled, focused, pressed, hovered;
} BtrcWaylandControlCanvas;

typedef struct {
    void (*destroy)(BtrcWaylandButton *button);
    int (*measure)(BtrcWaylandButton *button, bool horizontal, int forWidth);
    void (*paint)(BtrcWaylandButton *button, const BtrcWaylandControlCanvas *canvas);
    void (*setFont)(BtrcWaylandButton *button, double size, bool bold);
} BtrcWaylandButtonMethods;

/* Takes ownership of the state, including on allocation failure. Methods live
 * for the duration of the process. Rectangles are logical points. */
BtrcShimControl *btrcWaylandAdoptButton(unsigned id, BtrcWaylandButton *state, const BtrcWaylandButtonMethods *methods);
BtrcWaylandButton *btrcWaylandButtonState(BtrcShimControl *control);
void btrcWaylandControlChanged(BtrcShimControl *control);

/* Blend straight-alpha RGBA into the clipped scene at backing-pixel x,y. */
void btrcWaylandPaintPixel(const BtrcWaylandControlCanvas *canvas, int x, int y, const unsigned char color[4]);
#endif
