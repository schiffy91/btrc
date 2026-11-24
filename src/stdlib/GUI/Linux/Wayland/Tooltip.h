#ifndef BTRC_WAYLAND_TOOLTIP_H
#define BTRC_WAYLAND_TOOLTIP_H
#include "Window.h"

/* The popup owns its immutable raster until dismissal. */
bool btrcWaylandShowTooltip(BtrcWaylandWindow *window, const char *text, int x, int y, bool dark);
#endif
