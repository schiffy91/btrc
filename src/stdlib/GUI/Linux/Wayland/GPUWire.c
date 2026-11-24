#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "WirePrivate.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

/* The native display library is required by Vulkan/EGL to present on a
 * Wayland surface. Load its public C ABI on first GPU attachment only. An
 * ordinary window needs neither the library nor its development headers. */
struct wl_proxy;
struct wl_display;
struct wl_event_queue;
struct wl_interface;
struct wl_message {
    const char *name;
    const char *signature;
    const struct wl_interface **types;
};
struct wl_interface {
    const char *name;
    int version;
    int method_count;
    const struct wl_message *methods;
    int event_count;
    const struct wl_message *events;
};
struct wl_array { size_t size, alloc; void *data; };
union wl_argument {
    int32_t i;
    uint32_t u;
    int32_t f;
    const char *s;
    struct wl_proxy *o;
    uint32_t n;
    struct wl_array *a;
    int32_t h;
};
typedef int (*Dispatcher)(const void *, void *, uint32_t, const struct wl_message *, union wl_argument *);

typedef struct {
    struct wl_proxy *handle;
    const struct wl_interface *type;
} Proxy;

struct BtrcWaylandGPUWire {
    BtrcWaylandWire *wire;
    void *library;
    struct wl_display *display;
    struct wl_event_queue *queue;
    Proxy *objects;
    size_t capacity;
    Proxy *offers;
    size_t offerCapacity;
    bool restoringOffers;

    struct wl_display *(*connect)(int);
    void (*disconnect)(struct wl_display *);
    struct wl_event_queue *(*createQueue)(struct wl_display *);
    void (*destroyQueue)(struct wl_event_queue *);
    void (*setQueue)(struct wl_proxy *, struct wl_event_queue *);
    int (*prepare)(struct wl_display *, struct wl_event_queue *);
    void (*cancel)(struct wl_display *);
    int (*read)(struct wl_display *);
    int (*dispatch)(struct wl_display *, struct wl_event_queue *);
    int (*dispatchBlocking)(struct wl_display *, struct wl_event_queue *);
    int (*flush)(struct wl_display *);
    int (*error)(struct wl_display *);
    struct wl_proxy *(*create)(struct wl_proxy *, const struct wl_interface *);
    void (*destroy)(struct wl_proxy *);
    uint32_t (*id)(struct wl_proxy *);
    int (*listen)(struct wl_proxy *, Dispatcher, const void *, void *);
    struct wl_proxy *(*marshal)(struct wl_proxy *, uint32_t, const struct wl_interface *, uint32_t, uint32_t, union wl_argument *);
};

/* Non-core requests/events used by the window provider. Unused opcodes
 * occupy their specified positions. Core interfaces come from the loaded
 * driver-facing library. */
static const struct wl_interface *arguments[5];
static const struct wl_message shellRequests[] = {
    {"destroy", "", NULL}, {"create_positioner", "n", arguments},
    {"get_xdg_surface", "no", arguments}, {"pong", "u", arguments}
};
static const struct wl_message shellEvents[] = {{"ping", "u", arguments}};
static const struct wl_message surfaceRequests[] = {
    {"destroy", "", NULL}, {"get_toplevel", "n", arguments}, {"get_popup", "n?oo", arguments},
    {"set_window_geometry", "iiii", arguments}, {"ack_configure", "u", arguments}
};
static const struct wl_message surfaceEvents[] = {{"configure", "u", arguments}};
static const struct wl_message positionerRequests[] = {
    {"destroy", "", NULL}, {"set_size", "ii", arguments}, {"set_anchor_rect", "iiii", arguments},
    {"set_anchor", "u", arguments}, {"set_gravity", "u", arguments},
    {"set_constraint_adjustment", "u", arguments}, {"set_offset", "ii", arguments}
};
static const struct wl_message popupRequests[] = {{"destroy", "", NULL}};
static const struct wl_message popupEvents[] = {{"configure", "iiii", arguments}, {"popup_done", "", NULL}, {"repositioned", "u", arguments}};
static const struct wl_message toplevelRequests[] = {
    {"destroy", "", NULL}, {"set_parent", "?o", arguments}, {"set_title", "s", arguments},
    {"set_app_id", "s", arguments}, {"show_window_menu", "ouii", arguments}, {"move", "ou", arguments},
    {"resize", "ouu", arguments}, {"set_max_size", "ii", arguments}, {"set_min_size", "ii", arguments},
    {"set_maximized", "", NULL}, {"unset_maximized", "", NULL}, {"set_fullscreen", "?o", arguments},
    {"unset_fullscreen", "", NULL}, {"set_minimized", "", NULL}
};
static const struct wl_message toplevelEvents[] = {{"configure", "iia", arguments}, {"close", "", NULL},
    {"configure_bounds", "4ii", arguments}, {"wm_capabilities", "5a", arguments}};
static const struct wl_message cursorManagerRequests[] = {
    {"destroy", "", NULL}, {"get_pointer", "no", arguments}, {"get_tablet_tool_v2", "no", arguments}
};
static const struct wl_message cursorRequests[] = {{"destroy", "", NULL}, {"set_shape", "uu", arguments}};
static const struct wl_message textManagerRequests[] = {{"destroy", "", NULL}, {"get_text_input", "no", arguments}};
static const struct wl_message textRequests[] = {
    {"destroy", "", NULL}, {"enable", "", NULL}, {"disable", "", NULL}, {"set_surrounding_text", "sii", arguments},
    {"set_text_change_cause", "u", arguments}, {"set_content_type", "uu", arguments},
    {"set_cursor_rectangle", "iiii", arguments}, {"commit", "", NULL}
};
static const struct wl_message textEvents[] = {
    {"enter", "o", arguments}, {"leave", "o", arguments}, {"preedit_string", "?sii", arguments},
    {"commit_string", "?s", arguments}, {"delete_surrounding_text", "uu", arguments}, {"done", "u", arguments}
};
static const struct wl_message exporterRequestsV1[] = {{"destroy", "", NULL}, {"export", "no", arguments}};
static const struct wl_message exporterRequestsV2[] = {{"destroy", "", NULL}, {"export_toplevel", "no", arguments}};
static const struct wl_message exportedRequests[] = {{"destroy", "", NULL}};
static const struct wl_message exportedEvents[] = {{"handle", "s", arguments}};
static const struct wl_interface shellInterfaces[] = {
    {"zxdg_exporter_v1", 1, 2, exporterRequestsV1, 0, NULL}, {"zxdg_exporter_v2", 1, 2, exporterRequestsV2, 0, NULL},
    {"zxdg_exported_v1", 1, 1, exportedRequests, 1, exportedEvents}, {"zxdg_exported_v2", 1, 1, exportedRequests, 1, exportedEvents},
    {"zwp_text_input_manager_v3", 1, 2, textManagerRequests, 0, NULL},
    {"zwp_text_input_v3", 1, 8, textRequests, 6, textEvents},
    {"wp_cursor_shape_manager_v1", 1, 3, cursorManagerRequests, 0, NULL},
    {"wp_cursor_shape_device_v1", 1, 2, cursorRequests, 0, NULL},
    {"xdg_wm_base", 6, 4, shellRequests, 1, shellEvents},
    {"xdg_surface", 6, 5, surfaceRequests, 1, surfaceEvents},
    {"xdg_positioner", 6, 7, positionerRequests, 0, NULL}, {"xdg_popup", 6, 1, popupRequests, 3, popupEvents},
    {"xdg_toplevel", 6, 14, toplevelRequests, 4, toplevelEvents}
};

static const struct wl_interface *typeNamed(BtrcWaylandGPUWire *gpu, const char *name) {
    for (size_t i = 0; i < sizeof(shellInterfaces) / sizeof(shellInterfaces[0]); i++) {
        if (!strcmp(name, shellInterfaces[i].name)) { return &shellInterfaces[i]; }
    }
    char symbol[80];
    int size = snprintf(symbol, sizeof(symbol), "%s_interface", name);
    if (size < 0 || (size_t)size >= sizeof(symbol)) { return NULL; }
    return dlsym(gpu->library, symbol);
}

/* Keep dlsym's POSIX function-pointer conversion outside ISO C casts. */
static bool loadFunction(void *library, const char *name, void *slot, size_t size) {
    void *address = dlsym(library, name);
    if (!address || size != sizeof(address)) { return false; }
    memcpy(slot, &address, size);
    return true;
}

static bool loadAPI(BtrcWaylandGPUWire *gpu) {
#define LOAD(field, name) loadFunction(gpu->library, name, &gpu->field, sizeof(gpu->field))
    return LOAD(connect, "wl_display_connect_to_fd") && LOAD(disconnect, "wl_display_disconnect") &&
           LOAD(createQueue, "wl_display_create_queue") && LOAD(destroyQueue, "wl_event_queue_destroy") &&
           LOAD(setQueue, "wl_proxy_set_queue") && LOAD(prepare, "wl_display_prepare_read_queue") && LOAD(cancel, "wl_display_cancel_read") &&
           LOAD(read, "wl_display_read_events") && LOAD(dispatch, "wl_display_dispatch_queue_pending") &&
           LOAD(dispatchBlocking, "wl_display_dispatch_queue") &&
           LOAD(flush, "wl_display_flush") && LOAD(error, "wl_display_get_error") &&
           LOAD(create, "wl_proxy_create") && LOAD(destroy, "wl_proxy_destroy") &&
           LOAD(id, "wl_proxy_get_id") && LOAD(listen, "wl_proxy_add_dispatcher") &&
           LOAD(marshal, "wl_proxy_marshal_array_flags");
#undef LOAD
}

static bool append(BtrcWaylandWire *w, size_t *size, const void *data, size_t length) {
    size_t padded = (length + 3) & ~(size_t)3;
    if (length > MAX_MESSAGE || padded > MAX_MESSAGE - *size) { return false; }
    if (length) { memcpy(w->input + *size, data, length); }
    *size += padded;
    return true;
}

static bool remember(BtrcWaylandGPUWire *gpu, struct wl_proxy *proxy, const struct wl_interface *type);

static int forwardEvent(const void *context, void *target, uint32_t opcode, const struct wl_message *message, union wl_argument *values) {
    BtrcWaylandGPUWire *gpu = (BtrcWaylandGPUWire *)context;
    BtrcWaylandWire *w = gpu->wire;
    size_t size = 0;
    unsigned index = 0;
    bool valid = true;
    for (const char *s = message->signature; *s; s++) {
        if (*s == '?' || (*s >= '0' && *s <= '9')) { continue; }
        union wl_argument arg = values[index++];
        uint32_t word;
        switch (*s) {
        case 'h':
            if (w->fdCount == MAX_QUEUED_FDS) { close(arg.h); valid = false; }
            else { w->fds[w->fdCount++] = arg.h; }
            break;
        case 'a':
        case 's': {
            size_t length = *s == 'a' ? arg.a->size : arg.s ? strlen(arg.s) + 1 : 0;
            const void *bytes = *s == 'a' ? arg.a->data : (const void *)arg.s;
            word = (uint32_t)length;
            valid = valid && length <= MAX_MESSAGE && append(w, &size, &word, 4) && append(w, &size, bytes, length);
            break;
        }
        case 'n':
            if (!arg.o || !message->types || !message->types[index-1] ||
                !remember(gpu, arg.o, message->types[index-1])) { valid = false; break; }
            word = gpu->id(arg.o);
            valid = valid && append(w, &size, &word, 4);
            break;
        case 'o':
        case 'u':
        case 'i':
        case 'f':
            word = *s == 'o' ? (arg.o ? gpu->id(arg.o) : 0) : arg.u;
            valid = valid && append(w, &size, &word, 4);
            break;
        default: valid = false; break;
        }
    }
    if (gpu->restoringOffers) { return valid ? 0 : -1; }
    if (!valid || !btrcWaylandDispatchObject(w, gpu->id(target), opcode, w->input, size)) {
        btrcWaylandWireFail(w, "cannot dispatch native Wayland GPU display event");
        return -1;
    }
    return 0;
}

static Proxy *proxySlot(BtrcWaylandGPUWire *gpu, uint32_t id, bool grow) {
    bool offer = id >= SERVER_ID_BASE;
    size_t index = offer ? id - SERVER_ID_BASE : id;
    if (offer && index >= MAX_OFFERS) { return NULL; }
    Proxy **items = offer ? &gpu->offers : &gpu->objects;
    size_t *capacity = offer ? &gpu->offerCapacity : &gpu->capacity;
    if (index >= *capacity) {
        if (!grow) { return NULL; }
        size_t count = *capacity ? *capacity : 32;
        while (count <= index) { count *= 2; }
        Proxy *fresh = reallocarray(*items, count, sizeof(*fresh));
        if (!fresh) { return NULL; }
        memset(fresh + *capacity, 0, (count - *capacity) * sizeof(*fresh));
        *capacity = count;
        *items = fresh;
    }
    return &(*items)[index];
}

static bool remember(BtrcWaylandGPUWire *gpu, struct wl_proxy *proxy, const struct wl_interface *type) {
    uint32_t id = gpu->id(proxy);
    Proxy *slot = proxySlot(gpu, id, true);
    if (!slot || slot->handle) { return false; }
    if (id > 1) {
        gpu->setQueue(proxy, gpu->queue);
        if (gpu->listen(proxy, forwardEvent, gpu, NULL) < 0) { return false; }
    }
    *slot = (Proxy){proxy, type};
    return true;
}

uint32_t btrcWaylandGPUObject(BtrcWaylandGPUWire *gpu, const char *interface) {
    const struct wl_interface *type = typeNamed(gpu, interface);
    struct wl_proxy *proxy = type ? gpu->create((struct wl_proxy *)gpu->display, type) : NULL;
    if (!proxy) { return 0; }
    if (!remember(gpu, proxy, type)) { gpu->destroy(proxy); return 0; }
    return gpu->id(proxy);
}

void btrcWaylandGPURetire(BtrcWaylandGPUWire *gpu, uint32_t id) {
    Proxy *slot = proxySlot(gpu, id, false);
    if (id > 1 && slot && slot->handle) {
        gpu->destroy(slot->handle);
        *slot = (Proxy){0};
    }
}

void btrcWaylandGPUWireClose(BtrcWaylandGPUWire *gpu) {
    if (!gpu) { return; }
    for (size_t id = 2; id < gpu->capacity; id++) { btrcWaylandGPURetire(gpu, (uint32_t)id); }
    for (size_t i = 0; i < gpu->offerCapacity; i++) { btrcWaylandGPURetire(gpu, SERVER_ID_BASE + (uint32_t)i); }
    free(gpu->objects);
    free(gpu->offers);
    if (gpu->queue) { gpu->destroyQueue(gpu->queue); }
    if (gpu->display) { gpu->disconnect(gpu->display); }
    if (gpu->library) { dlclose(gpu->library); }
    free(gpu);
}

/* Only the library's event decoder can create a proxy with a server-owned ID.
 * Replay the already-delivered data_offer announcements on a private socket
 * before attaching the library to the real compositor. This retains lazy
 * clipboard sources, including on compositors that announce selection only
 * when focus changes. No requests or replay events go to the compositor. */
static bool restoreOffers(BtrcWaylandGPUWire *gpu, int peer, size_t count, uint32_t device) {
    BtrcWaylandWire *w = gpu->wire;
    gpu->restoringOffers = true;
    for (size_t i = 0; i < count; i++) {
        Object *offer = &w->offers[i];
        bool live = offer->allocated && !offer->retired;
        uint32_t object = SERVER_ID_BASE + (uint32_t)i;
        uint32_t message[] = {live ? offer->offerDevice : device, 12u << 16, object};
        ssize_t sent;
        do { sent = send(peer, message, sizeof(message), MSG_NOSIGNAL); } while (sent < 0 && errno == EINTR);
        if (sent != sizeof(message) || gpu->dispatchBlocking(gpu->display, gpu->queue) < 0 ||
            !btrcWaylandGPUProxy(gpu, object)) { return false; }
        if (!live) { btrcWaylandGPURetire(gpu, object); }
    }
    gpu->restoringOffers = false;
    return true;
}

bool btrcWaylandEnableGPUWire(BtrcWaylandWire *w) {
    if (w->gpu) { return true; }
    BtrcWaylandGPUWire *gpu = calloc(1, sizeof(*gpu));
    if (!gpu) { return false; }
    gpu->wire = w;
    gpu->library = dlopen("libwayland-client.so.0", RTLD_NOW | RTLD_LOCAL);
    bool ok = gpu->library && loadAPI(gpu) && btrcWaylandRoundtrip(w, 5000);
    long long until = btrcWaylandMilliseconds() + 5000;
    while (ok && (w->length || w->fdCount || w->first)) {
        long long left = until - btrcWaylandMilliseconds();
        ok = left > 0 && btrcWaylandPoll(w, (int)left) >= 0;
    }
    int staging[2] = {-1, -1};
    size_t offerCount = 0;
    uint32_t device = 0;
    for (size_t i = 0; i < w->offerCapacity; i++) {
        if (w->offers[i].allocated && !w->offers[i].retired) { offerCount = i + 1; device = w->offers[i].offerDevice; }
    }
    if (ok && offerCount) { ok = socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, staging) == 0; }
    if (ok) {
        int copy = offerCount ? staging[0] : fcntl(w->socket, F_DUPFD_CLOEXEC, 0);
        gpu->display = copy < 0 ? NULL : gpu->connect(copy);
        if (gpu->display) { gpu->queue = gpu->createQueue(gpu->display); }
        const struct wl_interface *displayType = typeNamed(gpu, "wl_display");
        ok = gpu->queue && displayType && remember(gpu, (struct wl_proxy *)gpu->display, displayType);
    }
    /* Construct genuine local proxies for the objects that already exist on
     * this connection. No requests go to the server during this step. Verify
     * every assigned ID before transferring ownership of reads and writes,
     * leaving the software transport usable if adoption ever fails. Holes
     * stay reserved in the library until the connection is closed. */
    for (uint32_t id = 2; ok && id < w->used; id++) {
        Object object = w->objects[id];
        uint32_t assigned = btrcWaylandGPUObject(gpu, object.interface ? object.interface : "wl_callback");
        ok = assigned == id;
        if (ok && (!object.allocated || object.retired)) { btrcWaylandGPURetire(gpu, id); }
    }
    if (ok && offerCount) {
        ok = restoreOffers(gpu, staging[1], offerCount, device) && dup3(w->socket, staging[0], O_CLOEXEC) == staging[0];
    }
    if (staging[1] >= 0) { close(staging[1]); }
    if (!ok) { btrcWaylandGPUWireClose(gpu); return false; }
    w->gpu = gpu;
    return true;
}

void *btrcWaylandGPUDisplay(BtrcWaylandGPUWire *gpu) { return gpu->display; }

void *btrcWaylandGPUProxy(BtrcWaylandGPUWire *gpu, uint32_t id) {
    Proxy *slot = proxySlot(gpu, id, false);
    return slot ? slot->handle : NULL;
}

bool btrcWaylandGPUSend(BtrcWaylandGPUWire *gpu, uint32_t id, unsigned opcode, const char *signature, va_list args) {
    Proxy *slot = proxySlot(gpu, id, false);
    if (!slot || !slot->handle || opcode >= (unsigned)slot->type->method_count) { return false; }
    Proxy proxy = *slot;
    const char *spec = proxy.type->methods[opcode].signature;
    union wl_argument values[16] = {0};
    unsigned count = 0;
    for (const char *s = spec; *s; s++) {
        if (*s == '?' || (*s >= '0' && *s <= '9')) { continue; }
        if (count == sizeof(values) / sizeof(values[0]) || !*signature) { return false; }
        union wl_argument *arg = &values[count++];
        char type = *signature++;
        if ((*s == 'n' || *s == 'o') && type == 'u') {
            uint32_t object = va_arg(args, uint32_t);
            arg->o = btrcWaylandGPUProxy(gpu, object);
            if (object && !arg->o) { return false; }
        } else if (type != *s) { return false; }
        else if (type == 'i') { arg->i = va_arg(args, int32_t); }
        else if (type == 'u') { arg->u = va_arg(args, uint32_t); }
        else if (type == 'h') { arg->h = va_arg(args, int); }
        else if (type == 's') { arg->s = va_arg(args, const char *); }
        else { return false; }
    }
    if (*signature) { return false; }
    gpu->marshal(proxy.handle, opcode, NULL, 0, 0, values);
    return !gpu->error(gpu->display) && btrcWaylandGPUFlush(gpu);
}

bool btrcWaylandGPUFlush(BtrcWaylandGPUWire *gpu) {
    return gpu->flush(gpu->display) >= 0 || errno == EAGAIN || btrcWaylandWireFail(gpu->wire, "cannot flush native Wayland display");
}

int btrcWaylandGPUPoll(BtrcWaylandGPUWire *gpu, int timeout) {
    BtrcWaylandWire *w = gpu->wire;
    int dispatched = gpu->dispatch(gpu->display, gpu->queue);
    if (dispatched < 0 || w->error[0]) { return -1; }
    if (dispatched > 0) { return 1; }
    /* A driver thread can read concurrently and queue application events.
     * Prepare the read before polling and end it on every exit path. */
    if (gpu->prepare(gpu->display, gpu->queue) < 0) { return gpu->error(gpu->display) ? -1 : 1; }
    int flushed = gpu->flush(gpu->display);
    if (flushed < 0 && errno != EAGAIN) { gpu->cancel(gpu->display); return -1; }
    struct pollfd fds[] = {{w->socket, POLLIN | (flushed < 0 ? POLLOUT : 0), 0}, {w->wake, POLLIN, 0}, {w->auxiliary, POLLIN, 0}, {w->accessibility, POLLIN, 0}};
    int ready = poll(fds, 4, timeout);
    int saved = errno;
    if (ready > 0 && (fds[0].revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL))) {
        if (gpu->read(gpu->display) < 0) { return -1; }
    } else { gpu->cancel(gpu->display); }
    if (ready <= 0) { return ready < 0 && saved != EINTR ? -1 : 0; }
    if (gpu->dispatch(gpu->display, gpu->queue) < 0 || w->error[0] || !btrcWaylandGPUFlush(gpu)) { return -1; }
    if (fds[1].revents & POLLIN) {
        uint64_t count;
        ssize_t n;
        do { n = read(w->wake, &count, sizeof(count)); } while (n < 0 && errno == EINTR);
        return n == sizeof(count) ? 2 : -1;
    }
    return 1;
}
