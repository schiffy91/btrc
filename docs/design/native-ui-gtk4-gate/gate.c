/* GTK4 gate spike, route 1: a WebGPU surface on a Wayland subsurface placed
 * below a GTK toplevel that is transparent where the surface shows. A native
 * button sits over it, both inside a scrolled window, with a web view beside. */
#include <gtk/gtk.h>
#include <gdk/wayland/gdkwayland.h>
#include <webkit/webkit.h>
#include <wayland-client.h>
#include <webgpu.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "viewporter-client-protocol.h"

typedef struct Gate {
    GtkWidget *window, *scroller, *hole, *web;
    struct wl_display *display;
    struct wl_event_queue *queue;
    struct wl_compositor *compositor;
    struct wl_subcompositor *subcompositor;
    struct wp_viewporter *viewporter;
    struct wl_surface *child;
    struct wl_subsurface *subsurface;
    struct wp_viewport *viewport;
    WGPUInstance instance;
    WGPUSurface surface;
    WGPUAdapter adapter;
    WGPUDevice device;
    WGPUQueue gpuQueue;
    WGPUTextureFormat format;
    int configuredWidth, configuredHeight;
    int frames, limit;
    gint64 last;
    double intervals[4096];
    double scrollTarget;
} Gate;

static void registryGlobal(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version) {
    Gate *gate = data;
    (void)version;
    if (strcmp(interface, wl_compositor_interface.name) == 0) gate->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4);
    else if (strcmp(interface, wl_subcompositor_interface.name) == 0) gate->subcompositor = wl_registry_bind(registry, name, &wl_subcompositor_interface, 1);
    else if (strcmp(interface, wp_viewporter_interface.name) == 0) gate->viewporter = wl_registry_bind(registry, name, &wp_viewporter_interface, 1);
}
static void registryRemove(void *data, struct wl_registry *registry, uint32_t name) { (void)data; (void)registry; (void)name; }
static const struct wl_registry_listener registryListener = {registryGlobal, registryRemove};

static void adapterReady(WGPURequestAdapterStatus status, WGPUAdapter adapter, WGPUStringView message, void *one, void *two) {
    (void)message; (void)two;
    if (status == WGPURequestAdapterStatus_Success) ((Gate *)one)->adapter = adapter;
}
static void deviceReady(WGPURequestDeviceStatus status, WGPUDevice device, WGPUStringView message, void *one, void *two) {
    (void)message; (void)two;
    if (status == WGPURequestDeviceStatus_Success) ((Gate *)one)->device = device;
}

static void attachGpu(Gate *gate) {
    GdkSurface *surface = gtk_native_get_surface(GTK_NATIVE(gate->window));
    gate->display = gdk_wayland_display_get_wl_display(gdk_surface_get_display(surface));
    struct wl_surface *parent = gdk_wayland_surface_get_wl_surface(surface);
    /* A private queue: binding globals must not dispatch GTK's own events. */
    gate->queue = wl_display_create_queue(gate->display);
    struct wl_display *wrapped = wl_proxy_create_wrapper(gate->display);
    wl_proxy_set_queue((struct wl_proxy *)wrapped, gate->queue);
    struct wl_registry *registry = wl_display_get_registry(wrapped);
    wl_proxy_wrapper_destroy(wrapped);
    wl_registry_add_listener(registry, &registryListener, gate);
    wl_display_roundtrip_queue(gate->display, gate->queue);
    if (!gate->compositor || !gate->subcompositor || !gate->viewporter) { fprintf(stderr, "GATE missing globals\n"); exit(2); }
    gate->child = wl_compositor_create_surface(gate->compositor);
    gate->subsurface = wl_subcompositor_get_subsurface(gate->subcompositor, gate->child, parent);
    wl_subsurface_place_below(gate->subsurface, parent);
    wl_subsurface_set_desync(gate->subsurface);
    gate->viewport = wp_viewporter_get_viewport(gate->viewporter, gate->child);
    /* The surface takes no input: the pointer goes to GTK above it. */
    struct wl_region *empty = wl_compositor_create_region(gate->compositor);
    wl_surface_set_input_region(gate->child, empty);
    wl_region_destroy(empty);

    WGPUInstanceDescriptor instanceDescriptor = {0};
    gate->instance = wgpuCreateInstance(&instanceDescriptor);
    WGPUSurfaceSourceWaylandSurface source = {.chain = {.sType = WGPUSType_SurfaceSourceWaylandSurface}, .display = gate->display, .surface = gate->child};
    WGPUSurfaceDescriptor surfaceDescriptor = {.nextInChain = &source.chain};
    gate->surface = wgpuInstanceCreateSurface(gate->instance, &surfaceDescriptor);
    WGPURequestAdapterOptions options = {.compatibleSurface = gate->surface};
    wgpuInstanceRequestAdapter(gate->instance, &options, (WGPURequestAdapterCallbackInfo){.callback = adapterReady, .userdata1 = gate});
    if (!gate->adapter) { fprintf(stderr, "GATE no adapter\n"); exit(2); }
    wgpuAdapterRequestDevice(gate->adapter, NULL, (WGPURequestDeviceCallbackInfo){.callback = deviceReady, .userdata1 = gate});
    if (!gate->device) { fprintf(stderr, "GATE no device\n"); exit(2); }
    gate->gpuQueue = wgpuDeviceGetQueue(gate->device);
    WGPUSurfaceCapabilities capabilities = {0};
    wgpuSurfaceGetCapabilities(gate->surface, gate->adapter, &capabilities);
    gate->format = capabilities.formats[0];
    WGPUAdapterInfo info = {0};
    wgpuAdapterGetInfo(gate->adapter, &info);
    fprintf(stderr, "GATE adapter=%.*s backend=%d\n", (int)info.device.length, info.device.data, (int)info.backendType);
}

static int compare(const void *left, const void *right) {
    double a = *(const double *)left, b = *(const double *)right;
    return a < b ? -1 : a > b;
}

static gboolean tick(GtkWidget *widget, GdkFrameClock *clock, gpointer data) {
    Gate *gate = data;
    (void)widget; (void)clock;
    if (!gate->child) attachGpu(gate);
    /* Where the hole is on the toplevel's surface, clipped to the scrolled window. */
    graphene_rect_t hole, clip;
    if (!gtk_widget_compute_bounds(gate->hole, gate->window, &hole) || !gtk_widget_compute_bounds(gate->scroller, gate->window, &clip)) return G_SOURCE_CONTINUE;
    double offsetX = 0, offsetY = 0;
    gtk_native_get_surface_transform(GTK_NATIVE(gate->window), &offsetX, &offsetY);
    graphene_rect_t visible;
    gboolean shown = graphene_rect_intersection(&hole, &clip, &visible);
    int scale = gtk_widget_get_scale_factor(gate->window);
    int width = (int)hole.size.width * scale, height = (int)hole.size.height * scale;
    if (shown && width > 0 && height > 0) {
        if (width != gate->configuredWidth || height != gate->configuredHeight) {
            WGPUSurfaceConfiguration configuration = {.device = gate->device, .format = gate->format, .usage = WGPUTextureUsage_RenderAttachment,
                .width = (uint32_t)width, .height = (uint32_t)height, .presentMode = WGPUPresentMode_Fifo, .alphaMode = WGPUCompositeAlphaMode_Auto};
            wgpuSurfaceConfigure(gate->surface, &configuration);
            gate->configuredWidth = width;
            gate->configuredHeight = height;
        }
        wl_subsurface_set_position(gate->subsurface, (int)(visible.origin.x + offsetX), (int)(visible.origin.y + offsetY));
        wp_viewport_set_source(gate->viewport, wl_fixed_from_double((visible.origin.x - hole.origin.x) * scale), wl_fixed_from_double((visible.origin.y - hole.origin.y) * scale),
            wl_fixed_from_double(visible.size.width * scale), wl_fixed_from_double(visible.size.height * scale));
        wp_viewport_set_destination(gate->viewport, (int)visible.size.width, (int)visible.size.height);
        WGPUSurfaceTexture texture;
        wgpuSurfaceGetCurrentTexture(gate->surface, &texture);
        if (texture.texture) {
            WGPUTextureView view = wgpuTextureCreateView(texture.texture, NULL);
            WGPUCommandEncoder encoder = wgpuDeviceCreateCommandEncoder(gate->device, NULL);
            double phase = (gate->frames % 120) / 120.0;
            WGPURenderPassColorAttachment attachment = {.view = view, .depthSlice = WGPU_DEPTH_SLICE_UNDEFINED, .loadOp = WGPULoadOp_Clear, .storeOp = WGPUStoreOp_Store,
                .clearValue = {0.0, 0.25 + 0.5 * phase, 1.0, 1.0}};
            WGPURenderPassDescriptor pass = {.colorAttachmentCount = 1, .colorAttachments = &attachment};
            WGPURenderPassEncoder encoded = wgpuCommandEncoderBeginRenderPass(encoder, &pass);
            wgpuRenderPassEncoderEnd(encoded);
            wgpuRenderPassEncoderRelease(encoded);
            WGPUCommandBuffer commands = wgpuCommandEncoderFinish(encoder, NULL);
            wgpuQueueSubmit(gate->gpuQueue, 1, &commands);
            wgpuSurfacePresent(gate->surface);
            wgpuCommandBufferRelease(commands);
            wgpuCommandEncoderRelease(encoder);
            wgpuTextureViewRelease(view);
            wgpuTextureRelease(texture.texture);
        }
    }
    /* The subsurface's position applies with the parent's next commit. */
    gtk_widget_queue_draw(gate->window);
    gint64 now = g_get_monotonic_time();
    if (gate->last && gate->frames < 4096) gate->intervals[gate->frames] = (now - gate->last) / 1000.0;
    gate->last = now;
    gate->frames++;
    if (gate->frames == gate->limit / 2) {
        GtkAdjustment *vertical = gtk_scrolled_window_get_vadjustment(GTK_SCROLLED_WINDOW(gate->scroller));
        gtk_adjustment_set_value(vertical, gate->scrollTarget);
    }
    if (gate->frames == gate->limit) {
        /* The first second is start-up: the web process, the device, first layout. */
        int first = 60, count = gate->frames - 1 - first, missed = 0;
        for (int index = first; index < first + count; index++) if (gate->intervals[index] > 25.0) missed++;
        qsort(gate->intervals + first, (size_t)count, sizeof(double), compare);
        fprintf(stderr, "GATE measured=%d interval-ms p50=%.2f p95=%.2f p99=%.2f max=%.2f missed=%d\n", count, gate->intervals[first + count / 2],
            gate->intervals[first + count * 95 / 100], gate->intervals[first + count * 99 / 100], gate->intervals[first + count - 1], missed);
        if (!getenv("GATE_HOLD")) { gtk_window_destroy(GTK_WINDOW(gate->window)); return G_SOURCE_REMOVE; }
    }
    return G_SOURCE_CONTINUE;
}

static void clicked(GtkButton *button, gpointer data) { (void)button; (void)data; fprintf(stderr, "GATE button clicked\n"); }

static void activate(GtkApplication *application, gpointer data) {
    Gate *gate = data;
    GtkCssProvider *css = gtk_css_provider_new();
    gtk_css_provider_load_from_string(css,
        "window { background: transparent; }"
        ".opaque { background: #303030; color: white; }"
        ".hole { background: transparent; }");
    gtk_style_context_add_provider_for_display(gdk_display_get_default(), GTK_STYLE_PROVIDER(css), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    gate->window = gtk_application_window_new(application);
    gtk_window_set_title(GTK_WINDOW(gate->window), "GTK4 gate");
    gtk_window_set_default_size(GTK_WINDOW(gate->window), 800, 400);
    gtk_window_set_decorated(GTK_WINDOW(gate->window), FALSE);
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gate->scroller = gtk_scrolled_window_new();
    gtk_widget_set_size_request(gate->scroller, 400, 400);
    GtkWidget *column = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkWidget *above = gtk_label_new("above the GPU surface");
    gtk_widget_add_css_class(above, "opaque");
    gtk_widget_set_size_request(above, 400, 60);
    GtkWidget *overlay = gtk_overlay_new();
    gate->hole = gtk_drawing_area_new();
    gtk_widget_add_css_class(gate->hole, "hole");
    gtk_widget_set_size_request(gate->hole, 400, 240);
    gtk_overlay_set_child(GTK_OVERLAY(overlay), gate->hole);
    GtkWidget *button = gtk_button_new_with_label("Native button over GPU");
    gtk_widget_set_halign(button, GTK_ALIGN_CENTER);
    gtk_widget_set_valign(button, GTK_ALIGN_CENTER);
    g_signal_connect(button, "clicked", G_CALLBACK(clicked), gate);
    gtk_overlay_add_overlay(GTK_OVERLAY(overlay), button);
    GtkWidget *below = gtk_label_new("below the GPU surface");
    gtk_widget_add_css_class(below, "opaque");
    gtk_widget_set_size_request(below, 400, 500);
    gtk_box_append(GTK_BOX(column), above);
    gtk_box_append(GTK_BOX(column), overlay);
    gtk_box_append(GTK_BOX(column), below);
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(gate->scroller), column);
    gate->web = webkit_web_view_new();
    gtk_widget_set_size_request(gate->web, 400, 400);
    webkit_web_view_load_html(WEBKIT_WEB_VIEW(gate->web),
        "<html><body style='margin:0;background:#1e7d32;color:white;font:24px sans-serif'><p style='padding:16px'>web view</p></body></html>", NULL);
    gtk_box_append(GTK_BOX(row), gate->scroller);
    gtk_box_append(GTK_BOX(row), gate->web);
    gtk_window_set_child(GTK_WINDOW(gate->window), row);
    gtk_widget_add_tick_callback(gate->window, tick, gate, NULL);
    gtk_window_present(GTK_WINDOW(gate->window));
}

int main(int argc, char **argv) {
    Gate gate = {0};
    gate.limit = getenv("GATE_FRAMES") ? atoi(getenv("GATE_FRAMES")) : 600;
    gate.scrollTarget = getenv("GATE_SCROLL") ? atof(getenv("GATE_SCROLL")) : 150.0;
    GtkApplication *application = gtk_application_new("dev.btrc.gate", G_APPLICATION_NON_UNIQUE);
    g_signal_connect(application, "activate", G_CALLBACK(activate), &gate);
    int status = g_application_run(G_APPLICATION(application), argc, argv);
    g_object_unref(application);
    return status;
}
