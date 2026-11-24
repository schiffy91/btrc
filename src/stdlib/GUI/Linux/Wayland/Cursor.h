#ifndef BTRC_WAYLAND_CURSOR_H
#define BTRC_WAYLAND_CURSOR_H
#include "Client.h"

typedef struct {
    uint32_t shapeDevice;
    uint32_t surface;
    uint32_t arrow;
    uint32_t text;
} BtrcWaylandCursor;

bool btrcWaylandCursorApply(BtrcWaylandDisplay *display, BtrcWaylandCursor *cursor, uint32_t pointer,
                            uint32_t serial, int kind);
void btrcWaylandCursorClose(BtrcWaylandDisplay *display, BtrcWaylandCursor *cursor);
#endif
