#ifndef BTRC_GUI_LINUX_VIEWPORT_H
#define BTRC_GUI_LINUX_VIEWPORT_H

#include <wayland-client.h>

/* The compositor advertises the stable viewporter v1 protocol. These
 * requests belong to the same connection as the window's wl_surface. */
extern const struct wl_interface btrcViewporterInterface;

struct wl_proxy* btrcViewportCreate(struct wl_proxy* viewporter, struct wl_surface* surface);
void btrcViewportResize(struct wl_proxy* viewport, int32_t width, int32_t height);
void btrcViewportDestroy(struct wl_proxy* viewport);

#endif
