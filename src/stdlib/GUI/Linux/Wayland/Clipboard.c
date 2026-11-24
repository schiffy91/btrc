#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "Clipboard.h"
#include "WirePrivate.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

struct BtrcClipboardText {
    _Atomic size_t refs;
    size_t size;
    char bytes[];
};
struct BtrcClipboardOffer {
    BtrcWaylandClipboard *clip;
    BtrcClipboardOffer *next;
    char *mime;
    unsigned rank;
    uint32_t id;
};
struct BtrcClipboardSource {
    BtrcClipboardSource *next;
    BtrcWaylandClipboard *clip;
    BtrcClipboardText *text;
    uint32_t id;
};
struct BtrcClipboardTransfer {
    BtrcClipboardTransfer *next;
    BtrcClipboardText *text;
    size_t offset;
    int fd;
};

static void release(BtrcClipboardText *text) {
    if (text && atomic_fetch_sub(&text->refs, 1) == 1) { free(text); }
}

static unsigned mimeRank(const char *mime) {
    if (!strcasecmp(mime, "text/plain;charset=utf-8")) { return 3; }
    if (!strcmp(mime, "UTF8_STRING")) { return 2; }
    return !strcasecmp(mime, "text/plain") ? 1u : 0u;
}

static void destroy(BtrcWaylandWire *wire, uint32_t id, unsigned opcode) {
    if (id) { btrcWaylandSend(wire, id, opcode, ""); btrcWaylandRetire(wire, id); }
}

static bool watch(BtrcWaylandDisplay *display, int fd, uint32_t events, void *owner) {
    BtrcWaylandWire *wire = display->wire;
    if (wire->auxiliary < 0) { wire->auxiliary = epoll_create1(EPOLL_CLOEXEC); }
    struct epoll_event event = {.events = events, .data.ptr = owner};
    return wire->auxiliary >= 0 && epoll_ctl(wire->auxiliary, EPOLL_CTL_ADD, fd, &event) == 0;
}

static void freeTransfer(BtrcWaylandDisplay *d, BtrcClipboardTransfer *t) {
    BtrcClipboardTransfer **where = &d->transfers;
    while (*where && *where != t) { where = &(*where)->next; }
    if (*where) { *where = t->next; }
    close(t->fd);
    release(t->text);
    free(t);
}

/* A receiver can close its pipe at any time. Keep the process's SIGPIPE
 * disposition and this thread's pre-existing pending signals intact. */
static ssize_t pipeWrite(int fd, const char *bytes, size_t size) {
    sigset_t signal, previous, pending;
    sigemptyset(&signal);
    sigaddset(&signal, SIGPIPE);
    if (pthread_sigmask(SIG_BLOCK, &signal, &previous)) { errno = EIO; return -1; }
    sigpending(&pending);
    ssize_t count = write(fd, bytes, size);
    int error = errno;
    if (count < 0 && error == EPIPE && !sigismember(&pending, SIGPIPE)) {
        struct timespec zero = {0};
        while (sigtimedwait(&signal, NULL, &zero) < 0 && errno == EINTR) { }
    }
    pthread_sigmask(SIG_SETMASK, &previous, NULL);
    errno = error;
    return count;
}

void btrcWaylandClipboardTransfers(BtrcWaylandDisplay *d) {
    if (!d->transfers || d->wire->auxiliary < 0) { return; }
    struct epoll_event events[16];
    int ready = epoll_wait(d->wire->auxiliary, events, 16, 0);
    for (int i = 0; i < ready; ++i) {
        BtrcClipboardTransfer *t = events[i].data.ptr;
        if (!t) { continue; } /* the synchronous reader has its own descriptor */
        size_t left = t->text->size - t->offset;
        ssize_t n = left ? pipeWrite(t->fd, t->text->bytes + t->offset, left < 65536 ? left : 65536) : 0;
        if (n > 0) { t->offset += (size_t)n; }
        if (t->offset == t->text->size || (!n && left) || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
            freeTransfer(d, t);
        }
    }
}

void btrcWaylandClipboardStop(BtrcWaylandDisplay *d) { while (d->transfers) { freeTransfer(d, d->transfers); } }

/* epoll cannot watch regular files. A recipient may supply one directly,
 * including a remote-mounted file. Do its writes away from the GUI thread.
 * The worker owns only its descriptor and an immutable text reference. */
static void *writeFile(void *context) {
    BtrcClipboardTransfer *transfer = context;
    size_t left = transfer->text->size;
    while (left) {
        size_t count = left < 65536 ? left : 65536;
        ssize_t n = write(transfer->fd, transfer->text->bytes + transfer->offset, count);
        if (n < 0 && errno == EINTR) { continue; }
        if (n <= 0) { break; }
        transfer->offset += (size_t)n;
        left -= (size_t)n;
    }
    close(transfer->fd);
    release(transfer->text);
    free(transfer);
    return NULL;
}

static void sendText(BtrcClipboardSource *source, int fd) {
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) { close(fd); return; }
    BtrcClipboardTransfer *transfer = calloc(1, sizeof(*transfer));
    if (!transfer) { close(fd); return; }
    transfer->fd = fd;
    transfer->text = source->text;
    atomic_fetch_add(&transfer->text->refs, 1);
    BtrcWaylandDisplay *display = source->clip->display;
    if (watch(display, fd, EPOLLOUT, transfer)) {
        transfer->next = display->transfers;
        display->transfers = transfer;
        return;
    }
    struct stat info;
    if (errno == EPERM && !fstat(fd, &info) && S_ISREG(info.st_mode)) {
        pthread_t worker;
        if (!pthread_create(&worker, NULL, writeFile, transfer)) { pthread_detach(worker); return; }
    }
    close(fd);
    release(transfer->text);
    free(transfer);
}

static void freeSource(BtrcClipboardSource *s) {
    BtrcWaylandClipboard *c = s->clip;
    BtrcClipboardSource **where = &c->sources;
    while (*where && *where != s) { where = &(*where)->next; }
    if (*where) { *where = s->next; }
    if (c->owner == s) { c->owner = NULL; }
    destroy(c->display->wire, s->id, 1);
    release(s->text);
    free(s);
}

static bool sourceEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *e) {
    (void)object;
    BtrcClipboardSource *s = owner;
    switch (opcode) {
    case 0: { uint32_t n; (void)btrcWaylandArray(e, &n); return true; }
    case 1: {
        const char *mime = btrcWaylandString(e);
        int fd = btrcWaylandFd(e);
        if (fd < 0) { return false; }
        if (!mimeRank(mime)) { close(fd); return true; }
        /* A peer closing its reader is local to its transfer. */
        sendText(s, fd);
        return true;
    }
    case 2: freeSource(s); return true;
    case 3: case 4: return true;
    case 5: (void)btrcWaylandUint(e); return true;
    default: return false;
    }
}

static bool publish(BtrcWaylandClipboard *c) {
    if (!c->device || !c->hasSerial || !c->pending) { return true; }
    BtrcClipboardSource *s = calloc(1, sizeof(*s));
    if (!s) { return false; }
    s->clip = c;
    BtrcWaylandWire *w = c->display->wire;
    s->id = btrcWaylandObject(w, "wl_data_source", s, sourceEvent, 1u << 1);
    if (!s->id || !btrcWaylandSend(w, c->display->dataManager, 0, "u", s->id) ||
        !btrcWaylandSend(w, s->id, 0, "s", "text/plain;charset=utf-8") ||
        !btrcWaylandSend(w, s->id, 0, "s", "text/plain") ||
        !btrcWaylandSend(w, s->id, 0, "s", "UTF8_STRING") ||
        !btrcWaylandSend(w, c->device, 1, "uu", s->id, c->serial)) {
        freeSource(s);
        return false;
    }
    s->text = c->pending;
    c->pending = NULL;
    s->next = c->sources;
    c->owner = c->sources = s;
    return true;
}

bool btrcWaylandClipboardSet(BtrcWaylandClipboard *c, const char *text) {
    if (!c || !c->device || !text) { return false; }
    size_t size = strlen(text);
    if (size > SIZE_MAX - sizeof(BtrcClipboardText) - 1) { return false; }
    BtrcClipboardText *value = malloc(sizeof(*value) + size + 1);
    if (!value) { return false; }
    value->refs = 1; value->size = size;
    memcpy(value->bytes, text, size + 1);
    release(c->pending);
    c->pending = value;
    return publish(c);
}

bool btrcWaylandClipboardSerial(BtrcWaylandClipboard *c, uint32_t serial) {
    c->hasSerial = true;
    c->serial = serial;
    return publish(c);
}

static void freeOffer(BtrcClipboardOffer *offer) {
    if (!offer) { return; }
    BtrcWaylandClipboard *c = offer->clip;
    BtrcClipboardOffer **where = &c->offers;
    while (*where && *where != offer) { where = &(*where)->next; }
    if (*where) { *where = offer->next; }
    if (c->selection == offer) { c->selection = NULL; }
    if (c->drag == offer) { c->drag = NULL; }
    destroy(c->display->wire, offer->id, 2);
    free(offer->mime);
    free(offer);
}

static bool offerEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *e) {
    (void)object;
    BtrcClipboardOffer *offer = owner;
    if (opcode == 1 || opcode == 2) { (void)btrcWaylandUint(e); return true; }
    if (opcode) { return false; }
    const char *mime = btrcWaylandString(e);
    unsigned rank = mimeRank(mime);
    if (rank > offer->rank) {
        char *copy = strdup(mime);
        if (!copy) { return false; }
        free(offer->mime);
        offer->mime = copy;
        offer->rank = rank;
    }
    return true;
}

static BtrcClipboardOffer *lookupOffer(BtrcWaylandClipboard *c, uint32_t id) {
    for (BtrcClipboardOffer *o = c->offers; o; o = o->next) { if (o->id == id) { return o; } }
    return NULL;
}

static bool deviceEvent(void *owner, uint32_t device, unsigned opcode, BtrcWaylandEvent *e) {
    BtrcWaylandClipboard *c = owner;
    switch (opcode) {
    case 0: {
        uint32_t id = btrcWaylandUint(e);
        BtrcClipboardOffer *o = calloc(1, sizeof(*o));
        if (!o || !btrcWaylandOfferObject(e->wire, device, id, o, offerEvent)) { free(o); return false; }
        o->clip = c; o->id = id; o->next = c->offers; c->offers = o;
        return true;
    }
    case 1:
        (void)btrcWaylandUint(e); (void)btrcWaylandUint(e);
        (void)btrcWaylandInt(e); (void)btrcWaylandInt(e);
        c->drag = lookupOffer(c, btrcWaylandUint(e)); return true;
    case 2: freeOffer(c->drag); return true;
    case 3: (void)btrcWaylandUint(e); (void)btrcWaylandInt(e); (void)btrcWaylandInt(e); return true;
    case 4: return true;
    case 5: {
        uint32_t id = btrcWaylandUint(e);
        BtrcClipboardOffer *selected = lookupOffer(c, id);
        if (selected != c->selection) { freeOffer(c->selection); c->selection = selected; }
        c->lostFocus = false;
        return !id || selected;
    }
    default: return false;
    }
}

bool btrcWaylandClipboardBind(BtrcWaylandClipboard *c, BtrcWaylandDisplay *d, uint32_t seat) {
    c->display = d;
    if (c->device || !d->dataManager) { return true; }
    c->device = btrcWaylandObject(d->wire, "wl_data_device", c, deviceEvent, 0);
    return c->device && btrcWaylandSend(d->wire, d->dataManager, 1, "uu", c->device, seat);
}

void btrcWaylandClipboardClose(BtrcWaylandClipboard *c) {
    while (c->offers) { freeOffer(c->offers); }
    while (c->sources) { freeSource(c->sources); }
    if (c->device) {
        if (c->display->dataVersion >= 2) { destroy(c->display->wire, c->device, 2); }
        else { btrcWaylandRetire(c->display->wire, c->device); }
    }
    release(c->pending);
}

bool btrcWaylandClipboardHas(BtrcWaylandClipboard *c) {
    return c && (c->pending || c->owner || (!c->lostFocus && c->selection && c->selection->mime));
}

char *btrcWaylandClipboardRead(BtrcWaylandClipboard *c) {
    if (!btrcWaylandClipboardHas(c)) { return NULL; }
    if (c->pending || c->owner) { return strdup((c->pending ? c->pending : c->owner->text)->bytes); }
    int fds[2];
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, fds)) { return NULL; }
    BtrcWaylandDisplay *d = c->display;
    bool ok = watch(d, fds[0], EPOLLIN, NULL) && btrcWaylandSend(d->wire, c->selection->id, 1, "sh", c->selection->mime, fds[1]);
    close(fds[1]);
    size_t used = 0, capacity = 0;
    char *text = NULL;
    long long deadline = btrcWaylandMilliseconds() + 1000;
    while (ok) {
        if (used + 1 >= capacity) {
            size_t size = capacity ? capacity * 2 : 4096;
            char *grown = size > capacity ? realloc(text, size) : NULL;
            if (!grown) { ok = false; break; }
            text = grown; capacity = size;
        }
        ssize_t count = recv(fds[0], text + used, capacity - used - 1, MSG_DONTWAIT);
        if (!count) { text[used] = 0; break; }
        if (count > 0) { used += (size_t)count; }
        else if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) { ok = false; break; }
        long long left = deadline - btrcWaylandMilliseconds();
        if (left <= 0) { ok = false; break; }
        if (count < 0 && errno != EINTR) { ok = btrcWaylandDisplayPoll(d, (int)left) >= 0; }
    }
    close(fds[0]);
    if (!ok) { free(text); return NULL; }
    return text;
}
