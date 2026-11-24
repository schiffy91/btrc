#include "GtkShimPrivate.h"
#include "PortalParent.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#ifdef GDK_WINDOWING_WAYLAND
#include <gdk/wayland/gdkwayland.h>
#endif
#ifdef GDK_WINDOWING_X11
#include <gdk/x11/gdkx.h>
#endif
#pragma GCC diagnostic pop

struct BtrcDialogParent {
    char *identifier;
    GWeakRef surface;
    unsigned references;
    bool released;
};

static void unrefParent(gpointer data) {
    BtrcDialogParent *parent = data;
    if (--parent->references) { return; }
    g_weak_ref_clear(&parent->surface);
    g_free(parent->identifier);
    g_free(parent);
}

#ifdef GDK_WINDOWING_WAYLAND
static void dropHandle(GdkToplevel *toplevel, const char *handle) {
#if GTK_CHECK_VERSION(4, 12, 0)
    gdk_wayland_toplevel_drop_exported_handle(toplevel, handle);
#else
    (void)handle;
    gdk_wayland_toplevel_unexport_handle(toplevel);
#endif
}

static void exported(GdkToplevel *surface, const char *handle, gpointer data) {
    BtrcDialogParent *parent = data;
    if (!handle || !*handle) { return; }
    if (parent->released) { dropHandle(surface, handle); return; }
    parent->identifier = g_strconcat("wayland:", handle, NULL);
}
#endif

BtrcDialogParent *btrcDialogParentOpen(BtrcShimWindow *window) {
    GtkWidget *widget = window ? btrcGtkWindowCanvas(window) : NULL;
    GtkNative *native = widget ? gtk_widget_get_native(widget) : NULL;
    GdkSurface *surface = native ? gtk_native_get_surface(native) : NULL;
    if (!surface || !gdk_surface_get_mapped(surface)) { return NULL; }
    BtrcDialogParent *parent = g_new0(BtrcDialogParent, 1);
    parent->references = 1;
    g_weak_ref_init(&parent->surface, surface);
#ifdef GDK_WINDOWING_WAYLAND
    if (GDK_IS_WAYLAND_TOPLEVEL(surface)) {
        if (gdk_wayland_toplevel_export_handle(GDK_TOPLEVEL(surface), exported, parent, unrefParent)) {
            parent->references++;
            return parent;
        }
    }
#endif
#ifdef GDK_WINDOWING_X11
    if (GDK_IS_X11_SURFACE(surface)) {
        G_GNUC_BEGIN_IGNORE_DEPRECATIONS
        parent->identifier = g_strdup_printf("x11:%lx", (unsigned long)gdk_x11_surface_get_xid(surface));
        G_GNUC_END_IGNORE_DEPRECATIONS
        return parent;
    }
#endif
    unrefParent(parent);
    return NULL;
}

const char *btrcDialogParentIdentifier(BtrcDialogParent *parent) { return parent->identifier; }

void btrcDialogParentRelease(BtrcDialogParent *parent) {
    if (!parent) { return; }
    parent->released = true;
#ifdef GDK_WINDOWING_WAYLAND
    GdkSurface *surface = g_weak_ref_get(&parent->surface);
    if (surface && GDK_IS_WAYLAND_TOPLEVEL(surface) && parent->identifier && !gdk_surface_is_destroyed(surface)) {
        dropHandle(GDK_TOPLEVEL(surface), parent->identifier + sizeof("wayland:") - 1);
    }
    if (surface) { g_object_unref(surface); }
#endif
    unrefParent(parent);
}
