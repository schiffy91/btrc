#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "WirePrivate.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

bool btrcWaylandWireFail(BtrcWaylandWire *w, const char *message) {
    if (!w->error[0]) { snprintf(w->error, sizeof(w->error), "%s", message); }
    return false;
}

long long btrcWaylandMilliseconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static int connectSocket(void) {
    const char *provided = getenv("WAYLAND_SOCKET");
    if (provided) {
        char *end;
        errno = 0;
        long number = strtol(provided, &end, 10);
        if (!*provided || *end || errno || number < 0 || number > INT_MAX) { errno = EINVAL; return -1; }
        int fd = (int)number;
        if (fcntl(fd, F_SETFD, FD_CLOEXEC) < 0) { return -1; }
        unsetenv("WAYLAND_SOCKET");
        return fd;
    }
    const char *name = getenv("WAYLAND_DISPLAY");
    if (!name || !*name) { name = "wayland-0"; }
    struct sockaddr_un address = {0};
    address.sun_family = AF_UNIX;
    int count;
    if (name[0] == '/') {
        count = snprintf(address.sun_path, sizeof(address.sun_path), "%s", name);
    } else {
        const char *directory = getenv("XDG_RUNTIME_DIR");
        if (!directory || directory[0] != '/') { errno = ENOENT; return -1; }
        count = snprintf(address.sun_path, sizeof(address.sun_path), "%s/%s", directory, name);
    }
    if (count < 0 || (size_t)count >= sizeof(address.sun_path)) { errno = ENAMETOOLONG; return -1; }
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) { return -1; }
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        int saved = errno;
        close(fd);
        errno = saved;
        return -1;
    }
    return fd;
}

uint32_t btrcWaylandUint(BtrcWaylandEvent *event) {
    uint32_t result = 0;
    if (event->left < 4) { event->valid = false; return 0; }
    memcpy(&result, event->data, 4);
    event->data += 4;
    event->left -= 4;
    return result;
}

int32_t btrcWaylandInt(BtrcWaylandEvent *event) { return (int32_t)btrcWaylandUint(event); }

const void *btrcWaylandArray(BtrcWaylandEvent *event, uint32_t *size) {
    *size = btrcWaylandUint(event);
    if (*size > MAX_MESSAGE) { event->valid = false; return NULL; }
    size_t padded = (*size + 3u) & ~3u;
    if (padded > event->left) { event->valid = false; return NULL; }
    const void *result = event->data;
    event->data += padded;
    event->left -= padded;
    return result;
}

const char *btrcWaylandString(BtrcWaylandEvent *event) {
    uint32_t size;
    const char *value = btrcWaylandArray(event, &size);
    if (!value || !size || value[size - 1] || memchr(value, 0, size - 1)) {
        event->valid = false;
        return "";
    }
    return value;
}

int btrcWaylandFd(BtrcWaylandEvent *event) {
    BtrcWaylandWire *w = event->wire;
    if (!w->fdCount) { event->valid = false; return -1; }
    int fd = w->fds[0];
    memmove(w->fds, w->fds + 1, --w->fdCount * sizeof(int));
    return fd;
}

static bool displayEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event) {
    (void)object;
    BtrcWaylandWire *w = owner;
    if (opcode == 0) {
        uint32_t failed = btrcWaylandUint(event);
        uint32_t code = btrcWaylandUint(event);
        const char *description = btrcWaylandString(event);
        snprintf(w->error, sizeof(w->error), "Wayland error %u on object %u: %.180s", code, failed, description);
        return false;
    }
    if (opcode != 1) { return false; }
    uint32_t id = btrcWaylandUint(event);
    if (id < 2 || id >= w->used || !w->objects[id].retired) { return false; }
    w->objects[id] = (Object){.nextFree = w->freeObject};
    w->freeObject = id;
    return true;
}

BtrcWaylandWire *btrcWaylandConnect(void) {
    BtrcWaylandWire *w = calloc(1, sizeof(*w));
    if (!w) { return NULL; }
    w->socket = connectSocket();
    w->wake = -1;
    w->auxiliary = -1;
    w->accessibility = -1;
    if (w->socket >= 0) {
        int flags = fcntl(w->socket, F_GETFL);
        if (flags >= 0 && fcntl(w->socket, F_SETFL, flags | O_NONBLOCK) == 0) {
            w->wake = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
        }
    }
    w->capacity = 32;
    w->objects = calloc(w->capacity, sizeof(Object));
    if (w->socket < 0 || w->wake < 0 || !w->objects) {
        int saved = errno;
        btrcWaylandDisconnect(w);
        errno = saved;
        return NULL;
    }
    w->used = 2;
    w->objects[1] = (Object){.owner = w, .dispatch = displayEvent, .allocated = true};
    return w;
}

const char *btrcWaylandError(const BtrcWaylandWire *w) { return w->error; }

void btrcWaylandDisconnect(BtrcWaylandWire *w) {
    if (!w) { return; }
    if (w->gpu) { btrcWaylandGPUWireClose(w->gpu); }
    if (w->socket >= 0) { close(w->socket); }
    if (w->wake >= 0) { close(w->wake); }
    if (w->auxiliary >= 0) { close(w->auxiliary); }
    for (size_t i = 0; i < w->fdCount; i++) { close(w->fds[i]); }
    while (w->first) {
        Request *next = w->first->next;
        if (w->first->fd >= 0) { close(w->first->fd); }
        free(w->first);
        w->first = next;
    }
    free(w->offers);
    free(w->objects);
    free(w);
}

uint32_t btrcWaylandObject(BtrcWaylandWire *w, const char *interface, void *owner, BtrcWaylandDispatch dispatch, uint32_t fdEvents) {
    if (w->error[0]) { return 0; }
    uint32_t id;
    if (w->gpu) {
        id = btrcWaylandGPUObject(w->gpu, interface);
        if (!id) { btrcWaylandWireFail(w, "cannot allocate native Wayland proxy"); return 0; }
    } else if (w->freeObject) {
        id = w->freeObject;
        w->freeObject = w->objects[id].nextFree;
    } else { id = w->used; }
    if (id >= w->capacity) {
        uint32_t capacity = w->capacity;
        while (capacity <= id) {
            if (capacity > 0x7f000000u) { btrcWaylandWireFail(w, "Wayland object ID space exhausted"); return 0; }
            capacity *= 2;
        }
        Object *grown = reallocarray(w->objects, capacity, sizeof(*grown));
        if (!grown) { btrcWaylandWireFail(w, "cannot grow Wayland object table"); return 0; }
        memset(grown + w->capacity, 0, (capacity - w->capacity) * sizeof(*grown));
        w->objects = grown;
        w->capacity = capacity;
    }
    if (id >= w->used) { w->used = id + 1; }
    w->objects[id] = (Object){.interface = interface, .owner = owner, .dispatch = dispatch, .fdEvents = fdEvents, .allocated = true};
    return id;
}

static Object *lookup(BtrcWaylandWire *w, uint32_t id) {
    if (id >= SERVER_ID_BASE) {
        uint32_t index = id - SERVER_ID_BASE;
        return index < w->offerCapacity && w->offers[index].allocated ? &w->offers[index] : NULL;
    }
    return id && id < w->used && w->objects[id].allocated ? &w->objects[id] : NULL;
}

bool btrcWaylandOfferObject(BtrcWaylandWire *w, uint32_t device, uint32_t id, void *owner, BtrcWaylandDispatch dispatch) {
    if (id < SERVER_ID_BASE || id - SERVER_ID_BASE >= MAX_OFFERS) { return false; }
    uint32_t index = id - SERVER_ID_BASE;
    if (index >= w->offerCapacity) {
        size_t count = w->offerCapacity ? w->offerCapacity : 8;
        while (count <= index) { count *= 2; }
        Object *grown = reallocarray(w->offers, count, sizeof(*grown));
        if (!grown) { return false; }
        memset(grown + w->offerCapacity, 0, (count - w->offerCapacity) * sizeof(*grown));
        w->offers = grown;
        w->offerCapacity = count;
    }
    if (w->offers[index].allocated && !w->offers[index].retired) { return false; }
    w->offers[index] = (Object){.allocated = true, .offerDevice = device, .interface = "wl_data_offer",
                                .owner = owner, .dispatch = dispatch};
    return true;
}

void btrcWaylandRetire(BtrcWaylandWire *w, uint32_t id) {
    Object *o = lookup(w, id);
    if (id > 1 && o) {
        if (w->gpu) { btrcWaylandGPURetire(w->gpu, id); }
        o->retired = true;
        o->owner = NULL;
    }
}

bool btrcWaylandSend(BtrcWaylandWire *w, uint32_t id, unsigned opcode, const char *signature, ...) {
    if (w->error[0]) { return false; }
    Object *o = lookup(w, id);
    if (!o || o->retired || opcode > UINT16_MAX) {
        return btrcWaylandWireFail(w, "invalid Wayland request object");
    }
    va_list args;
    if (w->gpu) {
        va_start(args, signature);
        bool ok = btrcWaylandGPUSend(w->gpu, id, opcode, signature, args);
        va_end(args);
        return ok;
    }
    size_t size = 8;
    va_start(args, signature);
    for (const char *s = signature; *s; s++) {
        size_t extra = 4;
        if (*s == 's') {
            const char *text = va_arg(args, const char *);
            size_t length = strnlen(text, MAX_MESSAGE);
            extra += (length + 4u) & ~(size_t)3u;
        } else if (*s == 'u') { (void)va_arg(args, uint32_t); }
        else if (*s == 'i') { (void)va_arg(args, int32_t); }
        else if (*s == 'h') { (void)va_arg(args, int); extra = 0; }
        else { va_end(args); return btrcWaylandWireFail(w, "unknown Wayland argument"); }
        if (extra > MAX_MESSAGE - size) { va_end(args); return btrcWaylandWireFail(w, "Wayland request exceeds wire size"); }
        size += extra;
    }
    va_end(args);
    if (w->queued + size > MAX_QUEUED_BYTES) { return btrcWaylandWireFail(w, "Wayland output queue is full"); }
    Request *r = calloc(1, sizeof(*r) + size);
    if (!r) { return btrcWaylandWireFail(w, "cannot allocate Wayland request"); }
    r->size = size;
    r->fd = -1;
    uint32_t header[2] = {id, (uint32_t)(size << 16) | opcode};
    memcpy(r->data, header, 8);
    size_t at = 8;
    va_start(args, signature);
    for (const char *s = signature; *s; s++) {
        uint32_t word;
        if (*s == 'h') {
            int original = va_arg(args, int);
            if (r->fd >= 0 || (r->fd = fcntl(original, F_DUPFD_CLOEXEC, 0)) < 0) {
                if (r->fd >= 0) { close(r->fd); }
                free(r);
                va_end(args);
                return btrcWaylandWireFail(w, "cannot queue Wayland descriptor");
            }
        } else if (*s == 's') {
            const char *text = va_arg(args, const char *);
            word = (uint32_t)strlen(text) + 1;
            memcpy(r->data + at, &word, 4);
            memcpy(r->data + at + 4, text, word);
            at += 4 + ((word + 3u) & ~3u);
        } else {
            word = *s == 'i' ? (uint32_t)va_arg(args, int32_t) : va_arg(args, uint32_t);
            memcpy(r->data + at, &word, 4);
            at += 4;
        }
    }
    va_end(args);
    if (w->last) { w->last->next = r; } else { w->first = r; }
    w->last = r;
    w->queued += size;
    return btrcWaylandFlush(w);
}

bool btrcWaylandFlush(BtrcWaylandWire *w) {
    if (w->error[0]) { return false; }
    if (w->gpu) { return btrcWaylandGPUFlush(w->gpu); }
    while (w->first) {
        Request *r = w->first;
        struct iovec data = {r->data + r->sent, r->size - r->sent};
        struct msghdr msg = {.msg_iov = &data, .msg_iovlen = 1};
        union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof(int))]; } control = {0};
        if (r->fd >= 0) {
            msg.msg_control = control.bytes;
            msg.msg_controllen = sizeof(control.bytes);
            struct cmsghdr *c = CMSG_FIRSTHDR(&msg);
            c->cmsg_level = SOL_SOCKET;
            c->cmsg_type = SCM_RIGHTS;
            c->cmsg_len = CMSG_LEN(sizeof(int));
            memcpy(CMSG_DATA(c), &r->fd, sizeof(int));
        }
        ssize_t n = sendmsg(w->socket, &msg, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) { continue; }
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) { return true; }
        if (n <= 0) { return btrcWaylandWireFail(w, "Wayland compositor closed while sending"); }
        if (r->fd >= 0) { close(r->fd); r->fd = -1; }
        r->sent += (size_t)n;
        w->queued -= (size_t)n;
        if (r->sent == r->size) {
            w->first = r->next;
            if (!w->first) { w->last = NULL; }
            free(r);
        }
    }
    return true;
}

bool btrcWaylandDispatchObject(BtrcWaylandWire *w, uint32_t id, unsigned opcode, const unsigned char *bytes, size_t size) {
    Object *found = lookup(w, id);
    if (!found) { return btrcWaylandWireFail(w, "unknown Wayland event object"); }
    Object object = *found;
    bool withFd = opcode < 32 && (object.fdEvents & (1u << opcode));
    if (withFd && !w->fdCount) { return btrcWaylandWireFail(w, "Wayland event has no descriptor"); }
    BtrcWaylandEvent e = {w, bytes, size, true};
    size_t expectedFds = w->fdCount - (withFd ? 1u : 0u);
    if (!object.retired) {
        if (!object.dispatch || !object.dispatch(object.owner, id, opcode, &e) || !e.valid || e.left || w->fdCount != expectedFds) {
            return btrcWaylandWireFail(w, "malformed Wayland event");
        }
    } else if (withFd) { close(btrcWaylandFd(&e)); }
    return true;
}

static bool dispatchFrames(BtrcWaylandWire *w) {
    size_t at = 0;
    while (w->length - at >= 8) {
        uint32_t header[2];
        memcpy(header, w->input + at, 8);
        uint32_t id = header[0];
        unsigned opcode = header[1] & 0xffffu;
        size_t size = header[1] >> 16;
        Object *found = lookup(w, id);
        if (size < 8 || (size & 3) || !found) {
            return btrcWaylandWireFail(w, "malformed Wayland event header");
        }
        if (size > w->length - at) { break; }
        Object object = *found;
        bool withFd = opcode < 32 && (object.fdEvents & (1u << opcode));
        if (withFd && !w->fdCount) { break; }
        if (!btrcWaylandDispatchObject(w, id, opcode, w->input + at + 8, size - 8)) { return false; }
        at += size;
    }
    if (at) { memmove(w->input, w->input + at, w->length - at); w->length -= at; }
    return true;
}

static bool receiveFrames(BtrcWaylandWire *w) {
    if (w->length == sizeof(w->input)) { return btrcWaylandWireFail(w, "incomplete Wayland message filled input buffer"); }
    struct iovec data = {w->input + w->length, sizeof(w->input) - w->length};
    union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof(int) * MAX_QUEUED_FDS)]; } control;
    struct msghdr msg = {.msg_iov = &data, .msg_iovlen = 1, .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes)};
    ssize_t n;
    do { n = recvmsg(w->socket, &msg, MSG_CMSG_CLOEXEC); } while (n < 0 && errno == EINTR);
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) { return true; }
    if (n <= 0) { return btrcWaylandWireFail(w, "Wayland compositor disconnected"); }
    bool overflow = !!(msg.msg_flags & MSG_CTRUNC);
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&msg); c; c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS) {
            size_t count = (c->cmsg_len - CMSG_LEN(0)) / sizeof(int);
            for (size_t i = 0; i < count; i++) {
                int fd;
                memcpy(&fd, CMSG_DATA(c) + i * sizeof(int), sizeof(fd));
                if (w->fdCount == MAX_QUEUED_FDS) { close(fd); overflow = true; }
                else { w->fds[w->fdCount++] = fd; }
            }
        }
    }
    if (overflow) { return btrcWaylandWireFail(w, "too many Wayland descriptors"); }
    w->length += (size_t)n;
    return dispatchFrames(w);
}

bool btrcWaylandWake(BtrcWaylandWire *w) {
    uint64_t one = 1;
    ssize_t written;
    do { written = write(w->wake, &one, sizeof(one)); } while (written < 0 && errno == EINTR);
    return written == sizeof(one) || (written < 0 && errno == EAGAIN);
}

int btrcWaylandPoll(BtrcWaylandWire *w, int timeout) {
    if (w->gpu) { return w->error[0] ? -1 : btrcWaylandGPUPoll(w->gpu, timeout); }
    if (!btrcWaylandFlush(w)) { return -1; }
    struct pollfd fds[] = {{w->socket, POLLIN | (w->first ? POLLOUT : 0), 0}, {w->wake, POLLIN, 0}, {w->auxiliary, POLLIN, 0}, {w->accessibility, POLLIN, 0}};
    int ready = poll(fds, 4, timeout);
    if (ready < 0 && errno == EINTR) { return 0; }
    if (ready < 0) { btrcWaylandWireFail(w, "Wayland poll failed"); return -1; }
    if (!ready) { return 0; }
    if (fds[0].revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL)) {
        if (!receiveFrames(w)) { return -1; }
    }
    if ((fds[0].revents & POLLOUT) && !btrcWaylandFlush(w)) { return -1; }
    if (fds[1].revents & POLLIN) {
        uint64_t count;
        ssize_t n;
        do { n = read(w->wake, &count, sizeof(count)); } while (n < 0 && errno == EINTR);
        return 2;
    }
    return 1;
}

static bool roundtripDone(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    if (opcode != 0) { return false; }
    (void)btrcWaylandUint(event);
    *(bool *)owner = true;
    btrcWaylandRetire(event->wire, id);
    return true;
}

bool btrcWaylandRoundtrip(BtrcWaylandWire *w, int timeout) {
    bool done = false;
    uint32_t callback = btrcWaylandObject(w, "wl_callback", &done, roundtripDone, 0);
    if (!callback || !btrcWaylandSend(w, 1, 0, "u", callback)) { return false; }
    long long deadline = btrcWaylandMilliseconds() + timeout;
    while (!done) {
        long long remaining = deadline - btrcWaylandMilliseconds();
        if (remaining <= 0 || btrcWaylandPoll(w, (int)remaining) < 0) {
            btrcWaylandRetire(w, callback);
            return false;
        }
    }
    return true;
}
