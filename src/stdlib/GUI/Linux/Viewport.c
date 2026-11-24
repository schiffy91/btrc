#include "Viewport.h"

/* viewporter.xml defines these wire requests in opcode order. Neither
 * interface has events. set_source occupies opcode 1 even though the
 * window uses only destination scaling. */
enum { viewportDestroy, viewportSetSource, viewportSetDestination };
enum { viewporterDestroy, viewporterGetViewport };

static const struct wl_interface* scalarArguments[4];
static const struct wl_message viewportRequests[] = {
    [viewportDestroy] = {"destroy", "", NULL},
    [viewportSetSource] = {"set_source", "ffff", scalarArguments},
    [viewportSetDestination] = {"set_destination", "ii", scalarArguments},
};
static const struct wl_interface viewportInterface = {
    "wp_viewport", 1, 3, viewportRequests, 0, NULL
};
static const struct wl_interface* creationArguments[] = {&viewportInterface, &wl_surface_interface};
static const struct wl_message viewporterRequests[] = {
    [viewporterDestroy] = {"destroy", "", NULL},
    [viewporterGetViewport] = {"get_viewport", "no", creationArguments},
};
const struct wl_interface btrcViewporterInterface = {
    "wp_viewporter", 1, 2, viewporterRequests, 0, NULL
};

struct wl_proxy* btrcViewportCreate(struct wl_proxy* viewporter, struct wl_surface* surface) {
    return wl_proxy_marshal_flags(viewporter, viewporterGetViewport, &viewportInterface,
                                  wl_proxy_get_version(viewporter), 0, NULL, surface);
}

void btrcViewportResize(struct wl_proxy* viewport, int32_t width, int32_t height) {
    wl_proxy_marshal_flags(viewport, viewportSetDestination, NULL, wl_proxy_get_version(viewport),
                           0, width, height);
}

void btrcViewportDestroy(struct wl_proxy* viewport) {
    wl_proxy_marshal_flags(viewport, viewportDestroy, NULL, wl_proxy_get_version(viewport),
                           WL_MARSHAL_FLAG_DESTROY);
}
