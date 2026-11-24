#ifndef BTRC_WAYLAND_TEXT_LINES_H
#define BTRC_WAYLAND_TEXT_LINES_H

#include "ControlText.h"

typedef struct BtrcWaylandTextLine BtrcWaylandTextLine;
typedef struct {
    BtrcWaylandTextLine **rows;
    size_t count, capacity;
    double width, height;
} BtrcWaylandTextLines;

/* Returns immutable native runs in reading order. Set width to -1 for natural
 * layout. Hard paragraph separators always break a line; wrapping uses the
 * Unicode word opportunities and leaves an indivisible word intact.
 * A NULL result means the configured provider cannot render all lines. */
BtrcWaylandTextLines *btrcWaylandShapeLines(BtrcSystemTextFont *font, const char *utf8, double width);
double btrcWaylandLineAdvance(const BtrcWaylandTextLines *lines, size_t index);
void btrcWaylandFreeLines(BtrcWaylandTextLines *lines);
void btrcWaylandPaintLines(const BtrcWaylandControlCanvas *canvas, const BtrcWaylandTextLines *lines,
                           double left, double top, double availableWidth, bool centered,
                           const unsigned char foreground[4]);
#endif
