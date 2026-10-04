/* Throwaway plain-C probe. No production provider or approved contract. */
#include <gtk/gtk.h>
#include <gdk/x11/gdkx.h>
#include <gdk/wayland/gdkwayland.h>
#include <wayland-client.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <webgpu.h>
#include <wgpu.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    WGPUInstance instance;
    WGPUAdapter adapter;
    WGPUDevice device;
    WGPUQueue queue;
    WGPUSurface surface;
    WGPUTextureFormat format;
    int mapped;
    unsigned frames;
} GPU;

static GPU gpu;
static struct wl_compositor *compositor;
static struct wl_subcompositor *subcompositor;
static unsigned live_widgets;

static void adapter_ready(WGPURequestAdapterStatus status, WGPUAdapter adapter,
                          WGPUStringView message, void *one, void *two) {
    (void)message; (void)one; (void)two;
    if (status != WGPURequestAdapterStatus_Success) exit(20);
    gpu.adapter = adapter;
}

static void device_ready(WGPURequestDeviceStatus status, WGPUDevice device,
                         WGPUStringView message, void *one, void *two) {
    (void)message; (void)one; (void)two;
    if (status != WGPURequestDeviceStatus_Success) exit(21);
    gpu.device = device;
}

static void mapped(WGPUMapAsyncStatus status, WGPUStringView message,
                   void *one, void *two) {
    (void)message; (void)one; (void)two;
    gpu.mapped = status == WGPUMapAsyncStatus_Success ? 1 : -1;
}

static void pump(void) {
    while (g_main_context_iteration(NULL, FALSE)) { }
    if (gpu.instance) wgpuInstanceProcessEvents(gpu.instance);
}

static void init_gpu(void) {
    WGPURequestAdapterOptions options = {.compatibleSurface = gpu.surface};
    wgpuInstanceRequestAdapter(gpu.instance, &options,
        (WGPURequestAdapterCallbackInfo){.mode = WGPUCallbackMode_AllowProcessEvents,
                                       .callback = adapter_ready});
    gint64 deadline = g_get_monotonic_time() + 10000000;
    while (!gpu.adapter && g_get_monotonic_time() < deadline) { pump(); g_usleep(1000); }
    if (!gpu.adapter) exit(22);
    wgpuAdapterRequestDevice(gpu.adapter, NULL,
        (WGPURequestDeviceCallbackInfo){.mode = WGPUCallbackMode_AllowProcessEvents,
                                      .callback = device_ready});
    while (!gpu.device && g_get_monotonic_time() < deadline) { pump(); g_usleep(1000); }
    if (!gpu.device) exit(23);
    gpu.queue = wgpuDeviceGetQueue(gpu.device);
    if (gpu.surface) {
        WGPUSurfaceCapabilities caps = {0};
        if (wgpuSurfaceGetCapabilities(gpu.surface, gpu.adapter, &caps) != WGPUStatus_Success || !caps.formatCount) exit(24);
        gpu.format = caps.formats[0];
        WGPUSurfaceConfiguration config = {.device = gpu.device, .format = gpu.format,
            .usage = WGPUTextureUsage_RenderAttachment, .width = 128, .height = 128,
            .presentMode = WGPUPresentMode_Fifo, .alphaMode = caps.alphaModes[0]};
        wgpuSurfaceConfigure(gpu.surface, &config);
        wgpuSurfaceCapabilitiesFreeMembers(caps);
    }
}

static void finish_gpu(void) {
    if (gpu.surface) { wgpuSurfaceUnconfigure(gpu.surface); wgpuSurfaceRelease(gpu.surface); }
    wgpuQueueRelease(gpu.queue);
    wgpuDeviceRelease(gpu.device);
    wgpuAdapterRelease(gpu.adapter);
    wgpuInstanceRelease(gpu.instance);
    gpu = (GPU){0};
}

static GdkTexture *frame(gboolean readback) {
    WGPUTexture texture;
    if (readback) {
        WGPUTextureDescriptor descriptor = {.dimension = WGPUTextureDimension_2D,
            .size = {128, 128, 1}, .format = WGPUTextureFormat_RGBA8Unorm,
            .mipLevelCount = 1, .sampleCount = 1,
            .usage = WGPUTextureUsage_RenderAttachment | WGPUTextureUsage_CopySrc};
        texture = wgpuDeviceCreateTexture(gpu.device, &descriptor);
    } else {
        WGPUSurfaceTexture next = {0};
        wgpuSurfaceGetCurrentTexture(gpu.surface, &next);
        if (!next.texture) exit(25);
        texture = next.texture;
    }
    WGPUTextureView view = wgpuTextureCreateView(texture, NULL);
    WGPUCommandEncoder encoder = wgpuDeviceCreateCommandEncoder(gpu.device, NULL);
    WGPURenderPassColorAttachment attachment = {.view = view,
        .depthSlice = WGPU_DEPTH_SLICE_UNDEFINED, .loadOp = WGPULoadOp_Clear,
        .storeOp = WGPUStoreOp_Store, .clearValue = {0.0, 0.25, 1.0, 1.0}};
    WGPURenderPassDescriptor pass_descriptor = {.colorAttachmentCount = 1, .colorAttachments = &attachment};
    WGPURenderPassEncoder pass = wgpuCommandEncoderBeginRenderPass(encoder, &pass_descriptor);
    wgpuRenderPassEncoderEnd(pass);
    wgpuRenderPassEncoderRelease(pass);
    WGPUBuffer buffer = NULL;
    if (readback) {
        WGPUBufferDescriptor descriptor = {.size = 128 * 128 * 4,
            .usage = WGPUBufferUsage_CopyDst | WGPUBufferUsage_MapRead};
        buffer = wgpuDeviceCreateBuffer(gpu.device, &descriptor);
        WGPUTexelCopyTextureInfo source = {.texture = texture, .aspect = WGPUTextureAspect_All};
        WGPUTexelCopyBufferInfo destination = {.buffer = buffer, .layout = {.bytesPerRow = 512, .rowsPerImage = 128}};
        WGPUExtent3D extent = {128,128,1};
        wgpuCommandEncoderCopyTextureToBuffer(encoder, &source, &destination, &extent);
    }
    WGPUCommandBuffer commands = wgpuCommandEncoderFinish(encoder, NULL);
    wgpuQueueSubmit(gpu.queue, 1, &commands);
    wgpuCommandBufferRelease(commands);
    wgpuCommandEncoderRelease(encoder);
    wgpuTextureViewRelease(view);
    GdkTexture *result = NULL;
    if (readback) {
        gpu.mapped = 0;
        wgpuBufferMapAsync(buffer, WGPUMapMode_Read, 0, 128 * 128 * 4,
            (WGPUBufferMapCallbackInfo){.mode = WGPUCallbackMode_AllowProcessEvents, .callback = mapped});
        gint64 deadline = g_get_monotonic_time() + 10000000;
        while (!gpu.mapped && g_get_monotonic_time() < deadline) {
            wgpuDevicePoll(gpu.device, FALSE, NULL); pump(); g_usleep(1000);
        }
        if (gpu.mapped != 1) exit(26);
        const unsigned char *pixels = wgpuBufferGetConstMappedRange(buffer, 0, 128 * 128 * 4);
        if (!pixels || pixels[2] != 255 || pixels[3] != 255) exit(27);
        GBytes *bytes = g_bytes_new(pixels, 128 * 128 * 4);
        result = gdk_memory_texture_new(128,128,GDK_MEMORY_R8G8B8A8,bytes,512);
        g_bytes_unref(bytes);
        wgpuBufferUnmap(buffer);
        wgpuBufferRelease(buffer);
    } else {
        if (wgpuSurfacePresent(gpu.surface) != WGPUStatus_Success) exit(28);
    }
    wgpuTextureRelease(texture);
    gpu.frames++;
    return result;
}

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
                            const char *interface, uint32_t version) {
    (void)data;
    if (!strcmp(interface,"wl_compositor")) compositor = wl_registry_bind(registry,name,&wl_compositor_interface,version < 4 ? version : 4);
    if (!strcmp(interface,"wl_subcompositor")) subcompositor = wl_registry_bind(registry,name,&wl_subcompositor_interface,1);
}
static void registry_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data; (void)registry; (void)name;
}
static const struct wl_registry_listener registry_listener = {registry_global,registry_remove};

static void gone(void *data, GObject *object) { (void)data; (void)object; live_widgets--; }
static GtkWidget *tracked(GtkWidget *widget) {
    live_widgets++; g_object_weak_ref(G_OBJECT(widget),gone,NULL); return widget;
}
static void setup_row(GtkSignalListItemFactory *factory, GtkListItem *item, void *data) {
    (void)factory; (void)data; gtk_list_item_set_child(item,gtk_label_new(NULL));
}
static void bind_row(GtkSignalListItemFactory *factory, GtkListItem *item, void *data) {
    (void)factory; (void)data;
    GtkStringObject *value = gtk_list_item_get_item(item);
    gtk_label_set_text(GTK_LABEL(gtk_list_item_get_child(item)),gtk_string_object_get_string(value));
}

static gboolean snapshot(GtkWidget *widget, const char *path) {
    GdkPaintable *paintable = gtk_widget_paintable_new(widget);
    GtkSnapshot *snap = gtk_snapshot_new();
    int width=gtk_widget_get_width(widget), height=gtk_widget_get_height(widget);
    gdk_paintable_snapshot(paintable,GDK_SNAPSHOT(snap),width,height);
    GskRenderNode *node=gtk_snapshot_free_to_node(snap);
    if (!node) exit(29);
    GskRenderer *renderer=gtk_native_get_renderer(gtk_widget_get_native(widget));
    graphene_rect_t area=GRAPHENE_RECT_INIT(0,0,width,height);
    GdkTexture *texture=gsk_renderer_render_texture(renderer,node,&area);
    gboolean saved=gdk_texture_save_to_png(texture,path);
    g_object_unref(texture); gsk_render_node_unref(node); g_object_unref(paintable);
    return saved;
}

int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr,"usage: Probe ROUTE CYCLES HOLD_SECONDS OUTPUT\n"); return 2; }
    const char *route=argv[1]; int cycles=atoi(argv[2]), hold=atoi(argv[3]);
    if (cycles < 1 || hold < 0) return 2;
    gtk_init();
    GdkDisplay *display=gdk_display_get_default();
    gboolean x11=GDK_IS_X11_DISPLAY(display), cpu=!strcmp(route,"cpu");
    if ((!strcmp(route,"x11-child") && !x11) || (!strcmp(route,"wayland-subsurface") && x11)) {
        printf("{\"route\":\"%s\",\"result\":\"protocol-not-applicable\",\"frames\":0}\n",route); return 0;
    }
    if (!strcmp(route,"dmabuf")) {
        printf("{\"route\":\"dmabuf\",\"result\":\"blocked-no-wgpu-c-export-api\",\"frames\":0,\"gtk_dmabuf_builder\":%s,\"gtk_graphics_offload\":%s}\n",
            gdk_dmabuf_texture_builder_get_type() ? "true":"false", gtk_graphics_offload_get_type() ? "true":"false");
        return 0;
    }
    if (!cpu && strcmp(route,"x11-child") && strcmp(route,"wayland-subsurface")) return 2;
    GtkApplication *application=gtk_application_new("org.btrc.GtkProbe",G_APPLICATION_NON_UNIQUE);
    GError *error=NULL;
    if (!g_application_register(G_APPLICATION(application),NULL,&error)) { fprintf(stderr,"%s\n",error->message); return 3; }
    unsigned total_frames=0;
    gint64 started=g_get_monotonic_time();
    for (int cycle=0;cycle<cycles;cycle++) {
        GtkWidget *window=tracked(gtk_application_window_new(application));
        gtk_window_set_title(GTK_WINDOW(window),"BTRC GTK4 WebGPU probe");
        gtk_window_set_default_size(GTK_WINDOW(window),480,540);
        GtkWidget *box=tracked(gtk_box_new(GTK_ORIENTATION_VERTICAL,4));
        gtk_window_set_child(GTK_WINDOW(window),box);
        gtk_box_append(GTK_BOX(box),tracked(gtk_entry_new()));
        GtkWidget *overlay=tracked(gtk_overlay_new());
        gtk_widget_set_size_request(overlay,128,128);
        gtk_widget_set_halign(overlay,GTK_ALIGN_START);
        gtk_widget_set_overflow(overlay,GTK_OVERFLOW_HIDDEN);
        GtkWidget *picture=tracked(gtk_picture_new());
        gtk_widget_set_size_request(picture,128,128);
        gtk_overlay_set_child(GTK_OVERLAY(overlay),picture);
        GtkWidget *button=tracked(gtk_button_new_with_label("Overlay"));
        gtk_widget_set_halign(button,GTK_ALIGN_START); gtk_widget_set_valign(button,GTK_ALIGN_START);
        gtk_overlay_add_overlay(GTK_OVERLAY(overlay),button);
        GtkWidget *gpu_clip=tracked(gtk_scrolled_window_new());
        gtk_widget_set_size_request(gpu_clip,96,96);
        gtk_widget_set_halign(gpu_clip,GTK_ALIGN_START);
        gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(gpu_clip),GTK_POLICY_EXTERNAL,GTK_POLICY_EXTERNAL);
        gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(gpu_clip),overlay);
        gtk_box_append(GTK_BOX(box),gpu_clip);
        GtkStringList *model=gtk_string_list_new(NULL);
        for (int row=0;row<1000;row++) { char label[40]; snprintf(label,sizeof label,"row-%04d",row); gtk_string_list_append(model,label); }
        GtkListItemFactory *factory=gtk_signal_list_item_factory_new();
        g_signal_connect(factory,"setup",G_CALLBACK(setup_row),NULL);
        g_signal_connect(factory,"bind",G_CALLBACK(bind_row),NULL);
        GtkWidget *list=tracked(gtk_list_view_new(GTK_SELECTION_MODEL(gtk_single_selection_new(G_LIST_MODEL(model))),factory));
        GtkWidget *scroll=tracked(gtk_scrolled_window_new());
        gtk_widget_set_vexpand(scroll,TRUE); gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),list);
        gtk_box_append(GTK_BOX(box),scroll);
        gtk_window_present(GTK_WINDOW(window));
        for (int n=0;n<50;n++) { pump(); g_usleep(1000); }
        GdkSurface *parent=gtk_native_get_surface(GTK_NATIVE(window));
        gpu.instance=wgpuCreateInstance(NULL);
        struct wl_surface *child=NULL; struct wl_subsurface *sub=NULL; struct wl_registry *registry=NULL;
        Window xchild=0;
        graphene_point_t origin=GRAPHENE_POINT_INIT(0,0), position;
        if (!gtk_widget_compute_point(overlay,window,&origin,&position)) return 4;
        if (!cpu && x11) {
            Display *xdpy=gdk_x11_display_get_xdisplay(display);
            xchild=XCreateSimpleWindow(xdpy,gdk_x11_surface_get_xid(parent),(int)position.x,(int)position.y,128,128,0,0,0);
            XMapWindow(xdpy,xchild); XSync(xdpy,FALSE);
            WGPUSurfaceSourceXlibWindow native={.chain={.sType=WGPUSType_SurfaceSourceXlibWindow},.display=xdpy,.window=xchild};
            WGPUSurfaceDescriptor descriptor={.nextInChain=&native.chain};
            gpu.surface=wgpuInstanceCreateSurface(gpu.instance,&descriptor);
        } else if (!cpu) {
            struct wl_display *wdpy=gdk_wayland_display_get_wl_display(display);
            registry=wl_display_get_registry(wdpy); wl_registry_add_listener(registry,&registry_listener,NULL); wl_display_roundtrip(wdpy);
            if (!compositor || !subcompositor) return 5;
            child=wl_compositor_create_surface(compositor);
            sub=wl_subcompositor_get_subsurface(subcompositor,child,gdk_wayland_surface_get_wl_surface(parent));
            wl_subsurface_set_position(sub,(int)position.x,(int)position.y); wl_subsurface_set_desync(sub);
            wl_surface_commit(gdk_wayland_surface_get_wl_surface(parent));
            WGPUSurfaceSourceWaylandSurface native={.chain={.sType=WGPUSType_SurfaceSourceWaylandSurface},.display=wdpy,.surface=child};
            WGPUSurfaceDescriptor descriptor={.nextInChain=&native.chain};
            gpu.surface=wgpuInstanceCreateSurface(gpu.instance,&descriptor);
        }
        init_gpu();
        for (int n=0;n<3;n++) {
            GdkTexture *texture=frame(cpu);
            if (texture) { gtk_picture_set_paintable(GTK_PICTURE(picture),GDK_PAINTABLE(texture)); g_object_unref(texture); }
            for (int tick=0;tick<20;tick++) { pump(); g_usleep(1000); }
        }
        if (cycle==0) {
            char png[4096]; snprintf(png,sizeof png,"%s/gtk-%s.png",argv[4],route);
            if (!snapshot(window,png)) return 6;
            if (x11) {
                Display *xdpy=gdk_x11_display_get_xdisplay(display);
                int width=gtk_widget_get_width(window),height=gtk_widget_get_height(window);
                XImage *image=XGetImage(xdpy,gdk_x11_surface_get_xid(parent),0,0,width,height,AllPlanes,ZPixmap);
                if (!image) return 8;
                unsigned char *pixels=g_malloc((size_t)width*height*4);
                for(int y=0;y<height;y++) for(int x=0;x<width;x++) {
                    unsigned long pixel=XGetPixel(image,x,y);
                    size_t offset=((size_t)y*width+x)*4;
                    pixels[offset]=(pixel>>16)&255; pixels[offset+1]=(pixel>>8)&255;
                    pixels[offset+2]=pixel&255; pixels[offset+3]=255;
                }
                GBytes *bytes=g_bytes_new_take(pixels,(size_t)width*height*4);
                GdkTexture *capture=gdk_memory_texture_new(width,height,GDK_MEMORY_R8G8B8A8,bytes,width*4);
                snprintf(png,sizeof png,"%s/x11-composed-%s.png",argv[4],route);
                if(!gdk_texture_save_to_png(capture,png)) return 9;
                g_object_unref(capture); g_bytes_unref(bytes); XDestroyImage(image);
            }
            for (int tick=0;tick<hold*100;tick++) { pump(); g_usleep(10000); }
        }
        total_frames+=gpu.frames;
        finish_gpu();
        if (xchild) { XDestroyWindow(gdk_x11_display_get_xdisplay(display),xchild); XSync(gdk_x11_display_get_xdisplay(display),FALSE); }
        if (sub) wl_subsurface_destroy(sub);
        if (child) wl_surface_destroy(child);
        if (registry) { wl_registry_destroy(registry); wl_subcompositor_destroy(subcompositor); wl_compositor_destroy(compositor); subcompositor=NULL; compositor=NULL; }
        gtk_window_destroy(GTK_WINDOW(window));
        for (int n=0;n<30;n++) { pump(); g_usleep(1000); }
        if (live_widgets) { fprintf(stderr,"owned widgets still alive: %u\n",live_widgets); return 7; }
        if ((cycle+1)%10==0) fprintf(stderr,"completed_cycles=%d frames=%u owned_widgets_alive=%u\n",cycle+1,total_frames,live_widgets);
    }
    g_object_unref(application);
    printf("{\"route\":\"%s\",\"protocol\":\"%s\",\"cycles\":%d,\"frames\":%u,\"owned_widgets_alive\":%u,\"elapsed_ms\":%.3f,\"snapshot_includes_gpu\":%s}\n",
        route,x11?"x11":"wayland",cycles,total_frames,live_widgets,(g_get_monotonic_time()-started)/1000.0,cpu?"true":"false");
    fflush(stdout);
    return 0;
}
