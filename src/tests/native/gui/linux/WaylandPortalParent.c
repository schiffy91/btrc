/* An independent portal-side client imports the handle from the native
 * window. It assigns a real xdg toplevel as its child and waits for the
 * compositor to revoke the imported relationship. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>
#include "xdg-shell.h"
#include "xdg-foreign-v1.h"
#include "xdg-foreign-v2.h"

static struct wl_compositor *compositor;
static struct xdg_wm_base *shell;
static struct zxdg_importer_v1 *manager1;
static struct zxdg_importer_v2 *manager2;
static int gone;

static void global(void *data, struct wl_registry *registry, uint32_t name, const char *type, uint32_t version) {
    (void)data; (void)version;
    if (!strcmp(type, "wl_compositor")) { compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 1); }
    if (!strcmp(type, "xdg_wm_base")) { shell = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1); }
    if (!strcmp(type, "zxdg_importer_v1")) { manager1 = wl_registry_bind(registry, name, &zxdg_importer_v1_interface, 1); }
    if (!strcmp(type, "zxdg_importer_v2")) { manager2 = wl_registry_bind(registry, name, &zxdg_importer_v2_interface, 1); }
}
static void removed(void *data, struct wl_registry *r, uint32_t name) { (void)data; (void)r; (void)name; }
static const struct wl_registry_listener registryListener = {global, removed};
static void destroyed1(void *data, struct zxdg_imported_v1 *item) { (void)data; (void)item; gone = 1; }
static void destroyed2(void *data, struct zxdg_imported_v2 *item) { (void)data; (void)item; gone = 1; }
static const struct zxdg_imported_v1_listener listener1 = {destroyed1};
static const struct zxdg_imported_v2_listener listener2 = {destroyed2};
static void configure(void *data, struct xdg_surface *xdg, uint32_t serial) { (void)data; xdg_surface_ack_configure(xdg, serial); }
static const struct xdg_surface_listener configureListener = {configure};

int main(int argc, char **argv) {
    assert(argc == 3 && !strncmp(argv[2], "wayland:", 8));
    struct wl_display *d = wl_display_connect(NULL);
    assert(d);
    struct wl_registry *r = wl_display_get_registry(d);
    wl_registry_add_listener(r, &registryListener, NULL);
    assert(wl_display_roundtrip(d) >= 0 && compositor && shell);
    struct wl_surface *surface = wl_compositor_create_surface(compositor);
    struct xdg_surface *xdg = xdg_wm_base_get_xdg_surface(shell, surface);
    xdg_surface_add_listener(xdg, &configureListener, NULL);
    struct xdg_toplevel *child = xdg_surface_get_toplevel(xdg);
    xdg_toplevel_set_title(child, "btrc child dialog");
    wl_surface_commit(surface);
    assert(wl_display_roundtrip(d) >= 0);
    if (strstr(argv[1], "v1")) {
        assert(manager1);
        struct zxdg_imported_v1 *parent = zxdg_importer_v1_import(manager1, argv[2]+8);
        zxdg_imported_v1_add_listener(parent, &listener1, NULL);
        zxdg_imported_v1_set_parent_of(parent, surface);
    } else {
        assert(manager2);
        struct zxdg_imported_v2 *parent = zxdg_importer_v2_import_toplevel(manager2, argv[2]+8);
        zxdg_imported_v2_add_listener(parent, &listener2, NULL);
        zxdg_imported_v2_set_parent_of(parent, surface);
    }
    assert(wl_display_roundtrip(d) >= 0 && !gone);
    puts("parent attached"); fflush(stdout);
    while (!gone) { assert(wl_display_dispatch(d) >= 0); }
    xdg_toplevel_destroy(child);
    xdg_surface_destroy(xdg);
    wl_surface_destroy(surface);
    wl_display_disconnect(d);
    return 0;
}
