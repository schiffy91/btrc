/* Exercise subsurface ordering without mapping either surface. Weston 15.0.1
 * asserts that applying the order dirtied a view, although no view exists. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>

struct globals {
    struct wl_compositor *compositor;
    struct wl_subcompositor *subcompositor;
};

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    struct globals *globals = data;
    (void)version;
    if (strcmp(interface, wl_compositor_interface.name) == 0) {
        globals->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 1);
    } else if (strcmp(interface, wl_subcompositor_interface.name) == 0) {
        globals->subcompositor = wl_registry_bind(registry, name, &wl_subcompositor_interface, 1);
    }
}

static void global_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data;
    (void)registry;
    (void)name;
}

int main(void) {
    struct wl_display *display = wl_display_connect(NULL);
    if (display == NULL) {
        fputs("cannot connect to compositor\n", stderr);
        return 1;
    }
    struct globals globals = {0};
    struct wl_registry *registry = wl_display_get_registry(display);
    const struct wl_registry_listener listener = {global, global_remove};
    int status = 1;
    wl_registry_add_listener(registry, &listener, &globals);
    if (wl_display_roundtrip(display) < 0 || globals.compositor == NULL || globals.subcompositor == NULL) {
        fputs("missing compositor or subsurface protocol\n", stderr);
        goto cleanup;
    }
    for (int cycle = 0; cycle < 100; ++cycle) {
        struct wl_surface *parent = wl_compositor_create_surface(globals.compositor);
        struct wl_surface *child = wl_compositor_create_surface(globals.compositor);
        struct wl_subsurface *subsurface = wl_subcompositor_get_subsurface(globals.subcompositor, child, parent);
        wl_subsurface_place_above(subsurface, parent);
        wl_surface_commit(child);
        wl_surface_commit(parent);
        int connected = wl_display_roundtrip(display);
        wl_subsurface_destroy(subsurface);
        wl_surface_destroy(child);
        wl_surface_destroy(parent);
        if (connected < 0 || wl_display_roundtrip(display) < 0) {
            fprintf(stderr, "compositor disconnected during unmapped cycle %d\n", cycle);
            goto cleanup;
        }
    }
    puts("100 unmapped subsurface cycles passed");
    status = 0;
cleanup:
    if (globals.subcompositor != NULL) wl_subcompositor_destroy(globals.subcompositor);
    if (globals.compositor != NULL) wl_compositor_destroy(globals.compositor);
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return status;
}
