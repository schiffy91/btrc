#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "Client.h"
#include "Clipboard.h"
#include "WirePrivate.h"

#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

struct BtrcWaylandGPUView {
    BtrcWaylandWindow *window;
    BtrcWaylandGPUView *next;
    uint32_t surface;
    uint32_t subsurface;
};

struct BtrcWaylandBuffer {
    BtrcWaylandWindow *window;
    BtrcWaylandBuffer *next;
    uint32_t object;
    int width;
    int height;
    void *memory;
    size_t size;
    bool busy;
    bool popup;
};

struct BtrcWaylandOutput {
    BtrcWaylandDisplay *display;
    BtrcWaylandOutput *next;
    uint32_t name;
    uint32_t object;
    uint32_t version;
    int scale;
    int pendingScale;
};

struct BtrcWaylandEntered {
    BtrcWaylandEntered *next;
    BtrcWaylandOutput *output;
};

struct BtrcWaylandExport {
    BtrcWaylandWindow *window;
    BtrcWaylandExport *next;
    uint32_t object;
    char *identifier;
};

struct BtrcWaylandQueuedEvent {
    BtrcWaylandQueuedEvent *next;
    BtrcShimEvent value;
};

static bool redraw(BtrcWaylandWindow *window);

bool btrcWaylandQueueEvent(BtrcWaylandDisplay *d, BtrcShimEvent event) {
    if (event.type != BTRC_SHIM_EVENT_USER && event.type != BTRC_SHIM_EVENT_WINDOW_EXPOSED) { ++d->arrivals; }
    if (d->modalFilter) {
        bool consumed = false;
        if (!d->modalFilter(d->modal, &event, &consumed)) { d->failed = true; return false; }
        if (consumed) { return true; }
    }
    if (d->routeInput && event.window && event.type < BTRC_SHIM_EVENT_CONTROL_ACTIVATED) {
        bool handled = false;
        if (!d->routeInput(d, &event, &handled)) { d->failed = true; return false; }
        if (handled) { return true; }
    }
    if (event.type == BTRC_SHIM_EVENT_MOUSE_MOTION && d->last && d->last->value.type == event.type && d->last->value.window == event.window) {
        d->last->value.x = event.x;
        d->last->value.y = event.y;
        return true;
    }
    if (d->queueSize >= 65536) { d->failed = true; return false; }
    BtrcWaylandQueuedEvent *item = calloc(1, sizeof(*item));
    if (!item) { d->failed = true; return false; }
    item->value = event;
    if (event.text && !(item->value.text = strdup(event.text))) { free(item); d->failed = true; return false; }
    if (d->last) { d->last->next = item; } else { d->first = item; }
    d->last = item;
    ++d->queueSize;
    return true;
}

bool btrcWaylandDisplayPop(BtrcWaylandDisplay *d, BtrcShimEvent *event) {
    if (!d->first || !event) { return false; }
    BtrcWaylandQueuedEvent *item = d->first;
    d->first = item->next;
    if (!d->first) { d->last = NULL; }
    --d->queueSize;
    free(d->lastText);
    d->lastText = (char *)item->value.text;
    *event = item->value;
    free(item);
    return true;
}

static bool windowEvent(BtrcWaylandWindow *w, unsigned type, int a, int b) {
    return btrcWaylandQueueEvent(w->display, (BtrcShimEvent){.type = type, .window = w->id, .data1 = a, .data2 = b});
}

static bool dimensions(int width, int height, int scale) {
    return width > 0 && height > 0 && scale > 0 &&
           width <= INT_MAX / 4 / scale && height <= INT_MAX / (width * scale * 4) / scale;
}

static void destroyRequest(BtrcWaylandWire *wire, uint32_t object, unsigned opcode) {
    if (!object) { return; }
    btrcWaylandSend(wire, object, opcode, "");
    btrcWaylandRetire(wire, object);
}

static void freeBuffer(BtrcWaylandBuffer *b) {
    destroyRequest(b->window->display->wire, b->object, 0);
    munmap(b->memory, b->size);
    free(b);
}

static void discardOldBuffers(BtrcWaylandWindow *w) {
    BtrcWaylandBuffer **where = &w->buffers;
    while (*where) {
        BtrcWaylandBuffer *b = *where;
        if (!b->busy && (b->width != w->width * w->scale || b->height != w->height * w->scale)) {
            *where = b->next;
            freeBuffer(b);
        } else { where = &b->next; }
    }
}

static bool changeSize(BtrcWaylandWindow *w, int width, int height, int scale) {
    if (!dimensions(width, height, scale)) { return false; }
    bool resized = w->width != width || w->height != height;
    bool scaled = w->scale != scale;
    if (!resized && !scaled) { return true; }
    w->width = width;
    w->height = height;
    w->scale = scale;
    free(w->pixels);
    w->pixels = NULL;
    w->dirty = true;
    discardOldBuffers(w);
    if (scaled) {
        for (BtrcWaylandGPUView *view = w->gpuViews; view; view = view->next) {
            if (!btrcWaylandSend(w->display->wire, view->surface, 8, "i", scale)) { return false; }
        }
    }
    if (scaled && !windowEvent(w, BTRC_SHIM_EVENT_WINDOW_DISPLAY_SCALE_CHANGED, scale, 0)) { return false; }
    if (resized && !windowEvent(w, BTRC_SHIM_EVENT_WINDOW_RESIZED, width, height)) { return false; }
    return windowEvent(w, BTRC_SHIM_EVENT_WINDOW_PIXEL_SIZE_CHANGED, width * scale, height * scale);
}

static bool outputScale(BtrcWaylandWindow *w) {
    int scale = w->preferredScale;
    if (!scale) {
        scale = 1;
        for (BtrcWaylandEntered *e = w->entered; e; e = e->next) {
            if (e->output->scale > scale) { scale = e->output->scale; }
        }
    }
    if (w->display->compositorVersion < 3) { scale = 1; }
    return changeSize(w, w->width, w->height, scale) && redraw(w);
}

BtrcWaylandWindow *btrcWaylandSurfaceWindow(BtrcWaylandDisplay *d, uint32_t surface) {
    for (BtrcWaylandWindow *w = d->windows; w; w = w->next) {
        if (w->surface == surface || btrcWaylandMenuSurface(w, surface)) { return w; }
    }
    return NULL;
}

static bool surfaceEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event) {
    (void)object;
    BtrcWaylandWindow *w = owner;
    if (opcode == 2) {
        w->preferredScale = btrcWaylandInt(event);
        return w->preferredScale > 0 && outputScale(w);
    }
    if (opcode == 3) { (void)btrcWaylandUint(event); return true; }
    if (opcode > 1) { return false; }
    uint32_t output = btrcWaylandUint(event);
    BtrcWaylandEntered **where = &w->entered;
    while (*where && (*where)->output->object != output) { where = &(*where)->next; }
    if (*where && opcode == 1) {
        BtrcWaylandEntered *old = *where;
        *where = old->next;
        free(old);
    } else if (!*where && opcode == 0) {
        for (BtrcWaylandOutput *out = w->display->outputs; out; out = out->next) {
            if (out->object != output) { continue; }
            BtrcWaylandEntered *added = calloc(1, sizeof(*added));
            if (!added) { return false; }
            added->output = out;
            *where = added;
            break;
        }
    }
    return outputScale(w);
}

static bool outputEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event) {
    (void)object;
    BtrcWaylandOutput *out = owner;
    switch (opcode) {
    case 0:
        for (unsigned i = 0; i < 5; i++) { (void)btrcWaylandInt(event); }
        (void)btrcWaylandString(event);
        (void)btrcWaylandString(event);
        (void)btrcWaylandInt(event);
        return true;
    case 1:
        for (unsigned i = 0; i < 4; i++) { (void)btrcWaylandUint(event); }
        return true;
    case 2:
        if (out->scale != out->pendingScale) {
            out->scale = out->pendingScale;
            for (BtrcWaylandWindow *w = out->display->windows; w; w = w->next) {
                if (!outputScale(w)) { return false; }
            }
        }
        return true;
    case 3: out->pendingScale = btrcWaylandInt(event); return out->pendingScale > 0;
    case 4:
    case 5: (void)btrcWaylandString(event); return true;
    default: return false;
    }
}

static bool shellEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event) {
    (void)owner;
    return opcode == 0 && btrcWaylandSend(event->wire, object, 3, "u", btrcWaylandUint(event));
}

static bool shmEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event) {
    (void)owner;
    (void)object;
    if (opcode != 0) { return false; }
    (void)btrcWaylandUint(event); /* ARGB8888 and XRGB8888 are mandatory. */
    return true;
}

static uint32_t bindGlobal(BtrcWaylandDisplay *d, uint32_t name, const char *interface, uint32_t version, void *owner, BtrcWaylandDispatch dispatch) {
    uint32_t id = btrcWaylandObject(d->wire, interface, owner, dispatch, 0);
    return id && btrcWaylandSend(d->wire, d->registry, 0, "usuu", name, interface, version, id) ? id : 0;
}

static void removeOutput(BtrcWaylandDisplay *d, uint32_t name) {
    BtrcWaylandOutput **where = &d->outputs;
    while (*where && (*where)->name != name) { where = &(*where)->next; }
    if (!*where) { return; }
    BtrcWaylandOutput *out = *where;
    *where = out->next;
    for (BtrcWaylandWindow *w = d->windows; w; w = w->next) {
        BtrcWaylandEntered **at = &w->entered;
        while (*at && (*at)->output != out) { at = &(*at)->next; }
        if (*at) {
            BtrcWaylandEntered *old = *at;
            *at = old->next;
            free(old);
            if (!outputScale(w)) { d->failed = true; }
        }
    }
    if (out->version >= 3) { destroyRequest(d->wire, out->object, 0); }
    else { btrcWaylandRetire(d->wire, out->object); }
    free(out);
}

static bool registryEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)id;
    BtrcWaylandDisplay *d = owner;
    uint32_t name = btrcWaylandUint(event);
    if (opcode == 1) {
        if (name == d->dialogManagerName) { d->dialogManagerName = 0; }
        if (name == d->subcompositorName) { d->subcompositorName = 0; }
        for (int i = 0; i < 2; ++i) {
            if (name == d->exporterName[i]) {
                d->exporterName[i] = 0;
                destroyRequest(d->wire, d->exporter[i], 0);
                d->exporter[i] = 0;
            }
        }
        removeOutput(d, name);
        btrcWaylandSeatRemove(d, name);
        return true;
    }
    if (opcode) { return false; }
    const char *interface = btrcWaylandString(event);
    uint32_t version = btrcWaylandUint(event);
    if (!event->valid || !version) { return false; }
    if (!strcmp(interface, "wl_compositor") && !d->compositor) {
        d->compositorVersion = version < 6 ? version : 6;
        return (d->compositor = bindGlobal(d, name, "wl_compositor", d->compositorVersion, d, NULL)) != 0;
    }
    if (!strcmp(interface, "zxdg_exporter_v2")) { d->exporterName[1] = name; return true; }
    if (!strcmp(interface, "zxdg_exporter_v1")) { d->exporterName[0] = name; return true; }
    if (!strcmp(interface, "wl_subcompositor")) { d->subcompositorName = name; return true; }
    if (!strcmp(interface, "wl_shm") && !d->shm) {
        return (d->shm = bindGlobal(d, name, "wl_shm", 1, d, shmEvent)) != 0;
    }
    if (!strcmp(interface, "xdg_wm_dialog_v1")) { d->dialogManagerName = name; return true; }
    if (!strcmp(interface, "wp_cursor_shape_manager_v1") && !d->cursorManager) {
        return (d->cursorManager = bindGlobal(d, name, "wp_cursor_shape_manager_v1", 1, d, NULL)) != 0;
    }
    if (!strcmp(interface, "zwp_text_input_manager_v3") && !d->textManager) {
        d->textManager = bindGlobal(d, name, "zwp_text_input_manager_v3", 1, d, NULL);
        return d->textManager && btrcWaylandBindTextInputs(d);
    }
    if (!strcmp(interface, "wl_data_device_manager") && !d->dataManager) {
        d->dataVersion = version < 3 ? version : 3;
        d->dataManager = bindGlobal(d, name, "wl_data_device_manager", d->dataVersion, d, NULL);
        return d->dataManager && btrcWaylandBindClipboards(d);
    }
    if (!strcmp(interface, "xdg_wm_base") && !d->shell) {
        return (d->shell = bindGlobal(d, name, "xdg_wm_base", version < 6 ? version : 6, d, shellEvent)) != 0;
    }
    if (!strcmp(interface, "wl_output")) {
        BtrcWaylandOutput *out = calloc(1, sizeof(*out));
        if (!out) { return false; }
        out->display = d;
        out->name = name;
        out->version = version < 4 ? version : 4;
        out->scale = out->pendingScale = 1;
        out->object = bindGlobal(d, name, "wl_output", out->version, out, outputEvent);
        out->next = d->outputs;
        d->outputs = out;
        return out->object != 0;
    }
    if (!strcmp(interface, "wl_seat")) { return btrcWaylandSeatBind(d, name, version); }
    return true;
}

BtrcWaylandDisplay *btrcWaylandDisplayOpen(void) {
    BtrcWaylandDisplay *d = calloc(1, sizeof(*d));
    if (!d) { return NULL; }
    d->wire = btrcWaylandConnect();
    if (!d->wire) { free(d); return NULL; }
    d->registry = btrcWaylandObject(d->wire, "wl_registry", d, registryEvent, 0);
    if (!d->registry || !btrcWaylandSend(d->wire, 1, 1, "u", d->registry) || !btrcWaylandRoundtrip(d->wire, 5000) ||
        !d->compositor || !d->shm || !d->shell || !btrcWaylandRoundtrip(d->wire, 5000)) {
        btrcWaylandDisplayClose(d);
        errno = EPROTO;
        return NULL;
    }
    return d;
}

int btrcWaylandDisplayPoll(BtrcWaylandDisplay *d, int timeout) {
    if (d->failed) { return -1; }
    int result = btrcWaylandPoll(d->wire, btrcWaylandRepeatTimeout(d, timeout));
    if (result < 0) { return -1; }
    if (result == 2 && !btrcWaylandQueueEvent(d, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_USER})) { return -1; }
    btrcWaylandClipboardTransfers(d);
    int repeated = btrcWaylandSendRepeats(d);
    return repeated < 0 || !result ? repeated : result;
}

bool btrcWaylandDisplayWake(BtrcWaylandDisplay *d) { return btrcWaylandWake(d->wire); }

const char *btrcWaylandDisplayError(BtrcWaylandDisplay *d) {
    return d->failed ? "Wayland window or event allocation failed" : btrcWaylandError(d->wire);
}

static bool bufferEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)id;
    (void)event;
    if (opcode) { return false; }
    BtrcWaylandBuffer *buffer = owner;
    BtrcWaylandWindow *w = buffer->window;
    buffer->busy = false;
    if (buffer->popup) { return true; }
    discardOldBuffers(w);
    return redraw(w);
}

static BtrcWaylandBuffer *newBuffer(BtrcWaylandWindow *w, int width, int height) {
    int size = width * height * 4;
    int fd = memfd_create("btrc-wayland-buffer", MFD_CLOEXEC);
    if (fd < 0) { return NULL; }
    void *memory = MAP_FAILED;
    if (ftruncate(fd, size) == 0) { memory = mmap(NULL, (size_t)size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0); }
    BtrcWaylandBuffer *b = memory != MAP_FAILED ? calloc(1, sizeof(*b)) : NULL;
    BtrcWaylandWire *wire = w->display->wire;
    uint32_t pool = b ? btrcWaylandObject(wire, "wl_shm_pool", NULL, NULL, 0) : 0;
    bool made = pool && btrcWaylandSend(wire, w->display->shm, 0, "uhi", pool, fd, size);
    close(fd);
    if (made) {
        b->object = btrcWaylandObject(wire, "wl_buffer", b, bufferEvent, 0);
        made = b->object && btrcWaylandSend(wire, pool, 0, "uiiiiu", b->object, 0, width, height, width * 4, 0u);
        destroyRequest(wire, pool, 1);
    }
    if (!made) {
        if (memory != MAP_FAILED) { munmap(memory, (size_t)size); }
        free(b);
        return NULL;
    }
    b->window = w;
    b->width = width;
    b->height = height;
    b->memory = memory;
    b->size = (size_t)size;
    b->next = w->buffers;
    w->buffers = b;
    return b;
}

static bool frameEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    if (opcode) { return false; }
    (void)btrcWaylandUint(event);
    BtrcWaylandWindow *w = owner;
    btrcWaylandRetire(event->wire, id);
    w->frame = 0;
    ++w->frames;
    return redraw(w);
}

static bool redraw(BtrcWaylandWindow *w) {
    if (!w->visible || !w->configured || !w->dirty || w->frame) { return true; }
    int width = w->width * w->scale;
    int height = w->height * w->scale;
    int count = 0;
    BtrcWaylandBuffer *b = w->buffers;
    while (b && (b->busy || b->width != width || b->height != height)) { ++count; b = b->next; }
    if (!b) {
        if (count >= 3) { return true; }
        b = newBuffer(w, width, height);
        if (!b) { return false; }
    }
    if (w->pixels) { memcpy(b->memory, w->pixels, b->size); }
    else {
        uint32_t *pixels = b->memory;
        for (size_t i = 0; i < b->size / 4; i++) { pixels[i] = 0xff000000u; }
    }
    BtrcWaylandWire *wire = w->display->wire;
    w->frame = btrcWaylandObject(wire, "wl_callback", w, frameEvent, 0);
    if (!w->frame || (w->display->compositorVersion >= 3 && !btrcWaylandSend(wire, w->surface, 8, "i", w->scale)) ||
        !btrcWaylandSend(wire, w->xdg, 3, "iiii", 0, 0, w->width, w->height) ||
        !btrcWaylandSend(wire, w->surface, 1, "uii", b->object, 0, 0) ||
        !btrcWaylandSend(wire, w->surface, 2, "iiii", 0, 0, w->width, w->height) ||
        !btrcWaylandSend(wire, w->surface, 3, "u", w->frame) || !btrcWaylandSend(wire, w->surface, 6, "")) { return false; }
    w->dirty = false;
    b->busy = true;
    if (!w->mapped) {
        w->mapped = true;
        return windowEvent(w, BTRC_SHIM_EVENT_WINDOW_SHOWN, 0, 0) && windowEvent(w, BTRC_SHIM_EVENT_WINDOW_EXPOSED, 0, 0);
    }
    return true;
}

static bool xdgEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    if (opcode) { return false; }
    BtrcWaylandWindow *w = owner;
    uint32_t serial = btrcWaylandUint(event);
    if (!btrcWaylandSend(event->wire, id, 4, "u", serial)) { return false; }
    w->configured = true;
    if (w->activated != w->configuredActivated) {
        w->activated = w->configuredActivated;
        if (w->display->activationChanged) { w->display->activationChanged(); }
    }
    if (w->suspended != w->configuredSuspended) {
        w->suspended = w->configuredSuspended;
        if (!windowEvent(w, w->suspended ? BTRC_SHIM_EVENT_WINDOW_MINIMIZED : BTRC_SHIM_EVENT_WINDOW_RESTORED, 0, 0)) { return false; }
    }
    return changeSize(w, w->configuredWidth ? w->configuredWidth : w->requestedWidth,
                      w->configuredHeight ? w->configuredHeight : w->requestedHeight, w->scale) && redraw(w);
}

static bool toplevelEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)id;
    BtrcWaylandWindow *w = owner;
    if (opcode == 1) { return windowEvent(w, BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED, 0, 0); }
    if (opcode == 2) { /* configure_bounds is a recommended maximum. */
        (void)btrcWaylandInt(event);
        (void)btrcWaylandInt(event);
        return true;
    }
    if (opcode == 3) { /* Window menu capabilities; no decoration menu here. */
        uint32_t size;
        (void)btrcWaylandArray(event, &size);
        return !(size & 3u);
    }
    if (opcode) { return false; }
    w->configuredWidth = btrcWaylandInt(event);
    w->configuredHeight = btrcWaylandInt(event);
    uint32_t size;
    const unsigned char *states = btrcWaylandArray(event, &size);
    if (!event->valid || (size & 3u)) { return false; }
    w->configuredActivated = false;
    w->configuredSuspended = false;
    for (size_t offset = 0; offset < size; offset += 4) {
        uint32_t state;
        memcpy(&state, states + offset, sizeof(state));
        if (state == 4) { w->configuredActivated = true; } /* xdg_toplevel.state.activated */
        if (state == 9) { w->configuredSuspended = true; } /* xdg_toplevel.state.suspended */
    }
    return w->configuredWidth >= 0 && w->configuredHeight >= 0;
}

BtrcWaylandWindow *btrcWaylandWindowCreate(BtrcWaylandDisplay *d, const char *title, int width, int height) {
    if (!title || !dimensions(width, height, 1) || d->nextWindow == UINT32_MAX) { return NULL; }
    BtrcWaylandWindow *w = calloc(1, sizeof(*w));
    if (!w) { return NULL; }
    w->display = d;
    w->id = ++d->nextWindow;
    w->width = w->requestedWidth = width;
    w->height = w->requestedHeight = height;
    w->scale = 1;
    w->textWidth = w->textHeight = 1;
    w->dirty = true;
    w->next = d->windows;
    d->windows = w;
    BtrcWaylandWire *wire = d->wire;
    w->surface = btrcWaylandObject(wire, "wl_surface", w, surfaceEvent, 0);
    w->xdg = btrcWaylandObject(wire, "xdg_surface", w, xdgEvent, 0);
    w->toplevel = btrcWaylandObject(wire, "xdg_toplevel", w, toplevelEvent, 0);
    if (!w->surface || !w->xdg || !w->toplevel ||
        !btrcWaylandSend(wire, d->compositor, 0, "u", w->surface) ||
        !btrcWaylandSend(wire, d->shell, 2, "uu", w->xdg, w->surface) ||
        !btrcWaylandSend(wire, w->xdg, 1, "u", w->toplevel) ||
        !btrcWaylandWindowTitle(w, title)) {
        btrcWaylandWindowDestroy(w);
        return NULL;
    }
    return w;
}

bool btrcWaylandWindowMakeDialog(BtrcWaylandWindow *w, BtrcWaylandWindow *owner) {
    if (!w || !owner || w == owner || w->display != owner->display || w->visible || w->dialog) { return false; }
    BtrcWaylandDisplay *d = w->display;
    if (!btrcWaylandSend(d->wire, w->toplevel, 1, "u", owner->toplevel)) { return false; }
    /* xdg_toplevel supplies the transient relationship on all desktops.
     * xdg-dialog adds a modal hint on compositors that advertise it. */
    if (!d->dialogManager && d->dialogManagerName) {
        d->dialogManager = bindGlobal(d, d->dialogManagerName, "xdg_wm_dialog_v1", 1, d, NULL);
        if (!d->dialogManager) { return false; }
    }
    if (!d->dialogManager) { return true; }
    w->dialog = btrcWaylandObject(d->wire, "xdg_dialog_v1", w, NULL, 0);
    return w->dialog && btrcWaylandSend(d->wire, d->dialogManager, 1, "uu", w->dialog, w->toplevel) &&
           btrcWaylandSend(d->wire, w->dialog, 1, "");
}

bool btrcWaylandWindowTitle(BtrcWaylandWindow *w, const char *title) {
    if (!title) { return false; }
    char *copy = strdup(title);
    if (!copy) { return false; }
    if (w->visible && !btrcWaylandSend(w->display->wire, w->toplevel, 2, "s", copy)) {
        free(copy);
        return false;
    }
    free(w->title);
    w->title = copy;
    return true;
}

bool btrcWaylandWindowMinimum(BtrcWaylandWindow *w, int width, int height) {
    if (width < 0 || height < 0) { return false; }
    w->minWidth = width;
    w->minHeight = height;
    return !w->visible || btrcWaylandSend(w->display->wire, w->toplevel, 8, "ii", width, height);
}

bool btrcWaylandWindowShow(BtrcWaylandWindow *w) {
    if (w->visible) { return true; }
    BtrcWaylandWire *wire = w->display->wire;
    if (!btrcWaylandSend(wire, w->toplevel, 2, "s", w->title) ||
        !btrcWaylandSend(wire, w->toplevel, 3, "s", "btrc") ||
        !btrcWaylandSend(wire, w->toplevel, 8, "ii", w->minWidth, w->minHeight) ||
        !btrcWaylandSend(wire, w->surface, 6, "")) { return false; }
    w->visible = true;
    w->dirty = true;
    return true;
}

bool btrcWaylandWindowHide(BtrcWaylandWindow *w) {
    btrcWaylandWindowClosePopup(w);
    if (!w->visible) { return true; }
    w->activated = w->configuredActivated = false;
    w->visible = w->configured = false;
    if (w->frame) { btrcWaylandRetire(w->display->wire, w->frame); w->frame = 0; }
    if (!btrcWaylandSend(w->display->wire, w->surface, 1, "uii", 0u, 0, 0) || !btrcWaylandSend(w->display->wire, w->surface, 6, "")) { return false; }
    if (w->mapped) {
        w->mapped = false;
        return windowEvent(w, BTRC_SHIM_EVENT_WINDOW_HIDDEN, 0, 0);
    }
    return true;
}

bool btrcWaylandWindowResize(BtrcWaylandWindow *w, int width, int height) {
    if (!dimensions(width, height, w->scale)) { return false; }
    w->requestedWidth = width;
    w->requestedHeight = height;
    return changeSize(w, width, height, w->scale) && redraw(w);
}

bool btrcWaylandWindowPaint(BtrcWaylandWindow *w, const uint32_t *pixels, int width, int height, size_t stride) {
    if (!pixels || width != w->width * w->scale || height != w->height * w->scale ||
        stride < (size_t)width * 4 || (height > 1 && stride > (SIZE_MAX - (size_t)width * 4) / (size_t)(height-1))) { return false; }
    if (!w->pixels) { w->pixels = malloc((size_t)width * height * 4); }
    if (!w->pixels) { return false; }
    for (int y = 0; y < height; y++) { memcpy(w->pixels + (size_t)y * width, (const unsigned char *)pixels + (size_t)y * stride, (size_t)width * 4); }
    w->dirty = true;
    return redraw(w);
}

int btrcWaylandWindowWidth(const BtrcWaylandWindow *w) { return w->width; }
int btrcWaylandWindowHeight(const BtrcWaylandWindow *w) { return w->height; }
int btrcWaylandWindowScale(const BtrcWaylandWindow *w) { return w->scale; }
uint32_t btrcWaylandWindowId(const BtrcWaylandWindow *w) { return w->id; }
unsigned btrcWaylandWindowFrames(const BtrcWaylandWindow *w) { return w->frames; }
void btrcWaylandWindowTextInput(BtrcWaylandWindow *w, bool active) {
    if (w->textInput == active) { return; }
    w->textInput = active;
    btrcWaylandUpdateTextInputs(w, false);
}
bool btrcWaylandWindowMapped(const BtrcWaylandWindow *w) { return w->mapped; }

static bool exportEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event) {
    (void)object;
    BtrcWaylandExport *token = owner;
    if (opcode || token->identifier) { return false; }
    const char *name = btrcWaylandString(event);
    if (!*name) { return false; }
    size_t size = strlen(name);
    token->identifier = malloc(size + sizeof("wayland:"));
    if (!token->identifier) { return false; }
    memcpy(token->identifier, "wayland:", 8);
    memcpy(token->identifier + 8, name, size + 1);
    return true;
}

static void revokeExport(BtrcWaylandExport *token) {
    BtrcWaylandWindow *w = token->window;
    if (!w) { return; }
    BtrcWaylandExport **where = &w->exports;
    while (*where && *where != token) { where = &(*where)->next; }
    if (*where) { *where = token->next; }
    destroyRequest(w->display->wire, token->object, 0);
    token->window = NULL;
}

BtrcWaylandExport *btrcWaylandWindowExport(BtrcWaylandWindow *w) {
    if (!w || !w->mapped) { return NULL; }
    BtrcWaylandDisplay *d = w->display;
    int version = d->exporterName[1] ? 1 : 0;
    if (!d->exporterName[version]) { return NULL; }
    if (!d->exporter[version]) {
        const char *manager = version ? "zxdg_exporter_v2" : "zxdg_exporter_v1";
        d->exporter[version] = bindGlobal(d, d->exporterName[version], manager, 1, d, NULL);
        if (!d->exporter[version]) { return NULL; }
    }
    BtrcWaylandExport *token = calloc(1, sizeof(*token));
    if (!token) { return NULL; }
    token->window = w;
    const char *interface = version ? "zxdg_exported_v2" : "zxdg_exported_v1";
    token->object = btrcWaylandObject(d->wire, interface, token, exportEvent, 0);
    if (!token->object || !btrcWaylandSend(d->wire, d->exporter[version], 1, "uu", token->object, w->surface)) {
        btrcWaylandExportRelease(token);
        return NULL;
    }
    token->next = w->exports;
    w->exports = token;
    return token;
}

const char *btrcWaylandExportIdentifier(const BtrcWaylandExport *token) {
    return token && token->window ? token->identifier : NULL;
}

void btrcWaylandExportRelease(BtrcWaylandExport *token) {
    if (!token) { return; }
    revokeExport(token);
    free(token->identifier);
    free(token);
}

static bool childSurfaceEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)owner;
    (void)id;
    /* The toplevel tracks outputs and scale for every child in its scene. */
    if (opcode > 3) { return false; }
    (void)btrcWaylandUint(event);
    return true;
}

typedef struct BtrcWaylandPopup {
    BtrcWaylandWindow *parent;
    uint32_t surface, xdg, role;
    int width, height, scale;
    bool configured;
    const BtrcWaylandMenuEvents *events;
    void *owner;
    BtrcWaylandBuffer *buffer;
} BtrcWaylandPopup;

bool btrcWaylandMenuSurface(const BtrcWaylandWindow *w, uint32_t surface) {
    return w->popup && w->popup->events && w->popup->surface == surface;
}

bool btrcWaylandMenuPointer(BtrcWaylandWindow *w, uint32_t surface, const BtrcShimEvent *event) {
    return !btrcWaylandMenuSurface(w, surface) || w->popup->events->input(w->popup->owner, event);
}

void btrcWaylandWindowClosePopup(BtrcWaylandWindow *w) {
    BtrcWaylandPopup *popup = w->popup;
    if (!popup) { return; }
    w->popup = NULL;
    destroyRequest(w->display->wire, popup->role, 0);
    destroyRequest(w->display->wire, popup->xdg, 0);
    destroyRequest(w->display->wire, popup->surface, 0);
    if (popup->buffer) { freeBuffer(popup->buffer); }
    free(popup);
}

static bool popupRoleEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)id;
    BtrcWaylandPopup *popup = owner;
    if (opcode == 0) {
        /* With side flipping and sliding (no resizing), x and y are chosen
         * by the compositor; the client does not move the parent. */
        for (int i = 0; i < 4; i++) { (void)btrcWaylandInt(event); }
    } else if (opcode == 1) {
        const BtrcWaylandMenuEvents *events = popup->events;
        void *target = popup->owner;
        btrcWaylandWindowClosePopup(popup->parent);
        return !events || events->dismissed(target);
    }
    else if (opcode == 2) { (void)btrcWaylandUint(event); }
    else { return false; }
    return true;
}

static bool popupConfigure(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    BtrcWaylandPopup *popup = owner;
    BtrcWaylandWindow *w = popup->parent;
    BtrcWaylandWire *wire = w->display->wire;
    if (opcode || !btrcWaylandSend(wire, id, 4, "u", btrcWaylandUint(event))) { return false; }
    popup->configured = true;
    bool ok = (w->display->compositorVersion < 3 || btrcWaylandSend(wire, popup->surface, 8, "i", popup->scale)) &&
              btrcWaylandSend(wire, popup->xdg, 3, "iiii", 0, 0, popup->width, popup->height) &&
              btrcWaylandSend(wire, popup->surface, 1, "uii", popup->buffer->object, 0, 0) &&
              btrcWaylandSend(wire, popup->surface, 2, "iiii", 0, 0, popup->width, popup->height) &&
              btrcWaylandSend(wire, popup->surface, 6, "");
    return ok;
}

static bool transparentInput(BtrcWaylandDisplay *d, uint32_t surface) {
    BtrcWaylandWire *wire = d->wire;
    uint32_t region = btrcWaylandObject(wire, "wl_region", NULL, NULL, 0);
    if (!region || !btrcWaylandSend(wire, d->compositor, 1, "u", region)) { return false; }
    bool ok = btrcWaylandSend(wire, surface, 5, "u", region);
    destroyRequest(wire, region, 0);
    return ok;
}

static bool showPopup(BtrcWaylandWindow *w, int x, int y, int anchorWidth, int anchorHeight, int width, int height,
                      const uint32_t *pixels, const BtrcWaylandMenuEvents *events, void *owner) {
    if (!w || !w->mapped || !pixels || !dimensions(width, height, w->scale)) { return false; }
    if (events && (!events->input || !events->dismissed || !w->activationSeat || !w->activationSerial)) { return false; }
    btrcWaylandWindowClosePopup(w);
    BtrcWaylandPopup *popup = calloc(1, sizeof(*popup));
    if (!popup) { return false; }
    w->popup = popup;
    popup->parent = w;
    popup->events = events;
    popup->owner = owner;
    popup->width = width;
    popup->height = height;
    popup->scale = w->scale;
    popup->buffer = newBuffer(w, width * w->scale, height * w->scale);
    if (!popup->buffer) { btrcWaylandWindowClosePopup(w); return false; }
    /* The popup owns its immutable frame until the surface is destroyed.
     * It never enters the parent's frame-reuse or resize path. */
    w->buffers = popup->buffer->next;
    popup->buffer->popup = true;
    memcpy(popup->buffer->memory, pixels, popup->buffer->size);
    BtrcWaylandDisplay *d = w->display;
    BtrcWaylandWire *wire = d->wire;
    x = x < 0 ? 0 : x >= w->width ? w->width - 1 : x;
    y = y < 0 ? 0 : y >= w->height ? w->height - 1 : y;
    if (anchorWidth > w->width - x) { anchorWidth = w->width - x; }
    if (anchorHeight > w->height - y) { anchorHeight = w->height - y; }
    uint32_t position = btrcWaylandObject(wire, "xdg_positioner", NULL, NULL, 0);
    if (!position || !btrcWaylandSend(wire, d->shell, 1, "u", position)) { goto failed; }
    popup->surface = btrcWaylandObject(wire, "wl_surface", popup, childSurfaceEvent, 0);
    if (!popup->surface || !btrcWaylandSend(wire, d->compositor, 0, "u", popup->surface) ||
        (!events && !transparentInput(d, popup->surface))) { goto failed; }
    popup->xdg = btrcWaylandObject(wire, "xdg_surface", popup, popupConfigure, 0);
    if (!popup->xdg || !btrcWaylandSend(wire, d->shell, 2, "uu", popup->xdg, popup->surface) ||
        !btrcWaylandSend(wire, position, 1, "ii", width, height) ||
        !btrcWaylandSend(wire, position, 2, "iiii", x, y, anchorWidth, anchorHeight) ||
        !btrcWaylandSend(wire, position, 3, "u", events ? 6u : 8u) || !btrcWaylandSend(wire, position, 4, "u", 8u) ||
        !btrcWaylandSend(wire, position, 5, "u", 1u|2u|4u|8u) ||
        !btrcWaylandSend(wire, position, 6, "ii", 0, events ? 0 : 12)) { goto failed; }
    popup->role = btrcWaylandObject(wire, "xdg_popup", popup, popupRoleEvent, 0);
    if (!popup->role || !btrcWaylandSend(wire, popup->xdg, 2, "uuu", popup->role, w->xdg, position) ||
        (events && !btrcWaylandSend(wire, popup->role, 1, "uu", w->activationSeat, w->activationSerial)) ||
        !btrcWaylandSend(wire, popup->surface, 6, "")) { goto failed; }
    destroyRequest(wire, position, 0);
    return true;
failed:
    destroyRequest(wire, position, 0);
    btrcWaylandWindowClosePopup(w);
    return false;
}

bool btrcWaylandWindowPopup(BtrcWaylandWindow *w, int x, int y, int width, int height, const uint32_t *pixels) {
    return showPopup(w, x, y, 1, 1, width, height, pixels, NULL, NULL);
}

bool btrcWaylandWindowMenu(BtrcWaylandWindow *w, int x, int y, int anchorWidth, int anchorHeight,
                           int width, int height, const uint32_t *pixels, size_t pixelCount, const BtrcWaylandMenuEvents *events, void *owner) {
    if (!w || !events || anchorWidth < 1 || anchorHeight < 1 || !dimensions(width, height, w->scale) ||
        pixelCount != (size_t)width * height * w->scale * w->scale) { return false; }
    return showPopup(w, x, y, anchorWidth, anchorHeight, width, height, pixels, events, owner);
}

bool btrcWaylandWindowUpdateMenu(BtrcWaylandWindow *w, const uint32_t *pixels, size_t pixelCount) {
    BtrcWaylandPopup *popup = w ? w->popup : NULL;
    if (!popup || !popup->events || !pixels || pixelCount != popup->buffer->size / sizeof(*pixels)) { return false; }
    BtrcWaylandBuffer *next = newBuffer(w, popup->width * popup->scale, popup->height * popup->scale);
    if (!next) { return false; }
    w->buffers = next->next;
    next->popup = true;
    memcpy(next->memory, pixels, next->size);
    BtrcWaylandWire *wire = w->display->wire;
    bool ok = !popup->configured || (btrcWaylandSend(wire, popup->surface, 1, "uii", next->object, 0, 0) &&
        btrcWaylandSend(wire, popup->surface, 2, "iiii", 0, 0, popup->width, popup->height) &&
        btrcWaylandSend(wire, popup->surface, 6, ""));
    if (!ok) { freeBuffer(next); return false; }
    freeBuffer(popup->buffer);
    popup->buffer = next;
    return true;
}

BtrcWaylandGPUView *btrcWaylandWindowAttachGPU(BtrcWaylandWindow *w, int x, int y) {
    BtrcWaylandDisplay *d = w->display;
    BtrcWaylandWire *wire = d->wire;
    if (!d->subcompositorName || !btrcWaylandEnableGPUWire(wire)) { return NULL; }
    if (!d->subcompositor) {
        d->subcompositor = bindGlobal(d, d->subcompositorName, "wl_subcompositor", 1, d, NULL);
        if (!d->subcompositor) { return NULL; }
    }
    BtrcWaylandGPUView *view = calloc(1, sizeof(*view));
    if (!view) { return NULL; }
    view->window = w;
    view->next = w->gpuViews;
    w->gpuViews = view;
    view->surface = btrcWaylandObject(wire, "wl_surface", view, childSurfaceEvent, 0);
    if (!view->surface || !btrcWaylandSend(wire, d->compositor, 0, "u", view->surface)) { goto failed; }
    view->subsurface = btrcWaylandObject(wire, "wl_subsurface", view, NULL, 0);
    if (!view->subsurface || !btrcWaylandSend(wire, d->subcompositor, 1, "uuu", view->subsurface, view->surface, w->surface) ||
        !btrcWaylandSend(wire, view->subsurface, 5, "") ||
        (d->compositorVersion >= 3 && !btrcWaylandSend(wire, view->surface, 8, "i", w->scale))) { goto failed; }
    if (!transparentInput(d, view->surface) || !btrcWaylandGPUViewMove(view, x, y)) { goto failed; }
    return view;

failed:
    btrcWaylandGPUViewDestroy(view);
    return NULL;
}

void *btrcWaylandGPUViewDisplay(BtrcWaylandGPUView *view) {
    return btrcWaylandGPUDisplay(view->window->display->wire->gpu);
}

void *btrcWaylandGPUViewSurface(BtrcWaylandGPUView *view) {
    return btrcWaylandGPUProxy(view->window->display->wire->gpu, view->surface);
}

bool btrcWaylandGPUViewPlaceBelowParent(BtrcWaylandGPUView *view) {
    BtrcWaylandWindow *w = view->window;
    return btrcWaylandSend(w->display->wire, view->subsurface, 3, "u", w->surface) &&
           btrcWaylandSend(w->display->wire, w->surface, 6, "");
}

bool btrcWaylandGPUViewMove(BtrcWaylandGPUView *view, int x, int y) {
    BtrcWaylandWindow *w = view->window;
    return btrcWaylandSend(w->display->wire, view->subsurface, 1, "ii", x, y) &&
           btrcWaylandSend(w->display->wire, w->surface, 6, "");
}

void btrcWaylandGPUViewDestroy(BtrcWaylandGPUView *view) {
    if (!view) { return; }
    BtrcWaylandWindow *w = view->window;
    BtrcWaylandGPUView **where = &w->gpuViews;
    while (*where && *where != view) { where = &(*where)->next; }
    if (*where) { *where = view->next; }
    destroyRequest(w->display->wire, view->subsurface, 0);
    destroyRequest(w->display->wire, view->surface, 0);
    free(view);
}

void btrcWaylandWindowDestroy(BtrcWaylandWindow *w) {
    if (!w) { return; }
    BtrcWaylandDisplay *d = w->display;
    BtrcWaylandWindow **where = &d->windows;
    while (*where && *where != w) { where = &(*where)->next; }
    if (*where) { *where = w->next; }
    btrcWaylandWindowClosePopup(w);
    while (w->exports) { revokeExport(w->exports); }
    while (w->gpuViews) { btrcWaylandGPUViewDestroy(w->gpuViews); }
    btrcWaylandSeatForget(d, w);
    if (w->frame) { btrcWaylandRetire(d->wire, w->frame); }
    destroyRequest(d->wire, w->dialog, 0);
    destroyRequest(d->wire, w->toplevel, 0);
    destroyRequest(d->wire, w->xdg, 0);
    destroyRequest(d->wire, w->surface, 0);
    while (w->buffers) { BtrcWaylandBuffer *b = w->buffers; w->buffers = b->next; freeBuffer(b); }
    while (w->entered) { BtrcWaylandEntered *e = w->entered; w->entered = e->next; free(e); }
    free(w->pixels);
    free(w->title);
    free(w);
}

void btrcWaylandDisplayClose(BtrcWaylandDisplay *d) {
    if (!d) { return; }
    while (d->windows) { btrcWaylandWindowDestroy(d->windows); }
    while (d->outputs) { removeOutput(d, d->outputs->name); }
    btrcWaylandSeatsClose(d);
    btrcWaylandClipboardStop(d);
    BtrcShimEvent event;
    while (btrcWaylandDisplayPop(d, &event)) { }
    free(d->lastText);
    btrcWaylandDisconnect(d->wire);
    free(d);
}
