#ifndef BTRC_WAYLAND_CONTROL_TEXT_H
#define BTRC_WAYLAND_CONTROL_TEXT_H
#include "ButtonHost.h"
#include "../../Text/SystemText.h"

typedef struct {
    BtrcSystemTextFont *font;
    BtrcSystemTextRun *run;
    double size, scale, width;
    int overflow;
    bool bold, tried;
} BtrcWaylandTextLayout;

typedef struct {
    char *value;
    BtrcWaylandTextLayout natural, display;
} BtrcWaylandControlText;

/* Zero-initialize before use. Setting the value invalidates prior runs.
 * Layout returns a borrowed run or NULL when the configured text provider
 * cannot shape this input. An empty string has no visual content. */
bool btrcWaylandSetControlText(BtrcWaylandControlText *text, const char *value);
void btrcWaylandFreeControlText(BtrcWaylandControlText *text);
BtrcSystemTextRun *btrcWaylandLayoutControlText(BtrcWaylandControlText *text, double logicalSize, bool bold,
                                                double scale, double maxWidth, int overflow);
/* The pen and baseline are in logical window coordinates. Mask coverage
 * takes the foreground colour; RGBA glyphs retain their colours. */
void btrcWaylandPaintTextRun(const BtrcWaylandControlCanvas *canvas, BtrcSystemTextRun *run,
                             double penX, double baselineY, const unsigned char foreground[4]);
#endif
