/* Prefer the compositor's themed cursor. On a core-protocol compositor an
 * immutable shared-memory image supplies the default and text shapes. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "Cursor.h"
#include <sys/mman.h>
#include <unistd.h>

static void destroy(BtrcWaylandWire *wire, uint32_t id, unsigned opcode) {
    if (id) {
        btrcWaylandSend(wire, id, opcode, "");
        btrcWaylandRetire(wire, id);
    }
}

static bool surfaceEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)owner;
    (void)id;
    if (opcode > 3) { return false; }
    (void)btrcWaylandUint(event);
    return true;
}

static bool bufferEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    (void)owner;
    (void)id;
    (void)event;
    return opcode == 0; /* release; the immutable pixels may be attached again */
}

enum { SIZE = 24 };
static bool shape(bool text, int x, int y) {
    if (text) {
        return ((x == 10 || x == 11) && y >= 3 && y <= 20) ||
               (x >= 7 && x <= 14 && (y == 3 || y == 20));
    }
    return (x >= 2 && x <= y && x <= 14 && y >= 2 && y <= 17 && (x <= 6 || x >= y - 4)) ||
           (y >= 13 && y <= 21 && x >= y / 2 - 1 && x <= y / 2 + 1);
}

static uint32_t cursorBuffer(BtrcWaylandDisplay *d, bool text) {
    uint32_t pixels[SIZE][SIZE] = {{0}};
    for (int y = 0; y < SIZE; y++) {
        for (int x = 0; x < SIZE; x++) {
            if (shape(text, x, y)) { pixels[y][x] = 0xff191919u; }
            else if (shape(text, x-1, y) || shape(text, x+1, y) || shape(text, x, y-1) || shape(text, x, y+1)) {
                pixels[y][x] = 0xffffffffu;
            }
        }
    }
    int fd = memfd_create("btrc-wayland-cursor", MFD_CLOEXEC);
    if (fd < 0) { return 0; }
    uint32_t pool = 0, buffer = 0;
    if (write(fd, pixels, sizeof(pixels)) == (ssize_t)sizeof(pixels)) {
        pool = btrcWaylandObject(d->wire, "wl_shm_pool", NULL, NULL, 0);
        if (pool && btrcWaylandSend(d->wire, d->shm, 0, "uhi", pool, fd, (int)sizeof(pixels))) {
            buffer = btrcWaylandObject(d->wire, "wl_buffer", NULL, bufferEvent, 0);
            if (buffer && !btrcWaylandSend(d->wire, pool, 0, "uiiiiu", buffer, 0, SIZE, SIZE, SIZE * 4, 0u)) {
                btrcWaylandRetire(d->wire, buffer);
                buffer = 0;
            }
            destroy(d->wire, pool, 1);
        }
    }
    close(fd);
    return buffer;
}

bool btrcWaylandCursorApply(BtrcWaylandDisplay *d, BtrcWaylandCursor *c, uint32_t pointer, uint32_t serial, int kind) {
    bool text = kind == BTRC_SHIM_CURSOR_TEXT;
    if (d->cursorManager) {
        if (!c->shapeDevice) {
            c->shapeDevice = btrcWaylandObject(d->wire, "wp_cursor_shape_device_v1", NULL, NULL, 0);
            if (!c->shapeDevice || !btrcWaylandSend(d->wire, d->cursorManager, 1, "uu", c->shapeDevice, pointer)) { return false; }
        }
        return btrcWaylandSend(d->wire, c->shapeDevice, 1, "uu", serial, text ? 9u : 1u);
    }
    if (!c->surface) {
        c->surface = btrcWaylandObject(d->wire, "wl_surface", NULL, surfaceEvent, 0);
        if (!c->surface || !btrcWaylandSend(d->wire, d->compositor, 0, "u", c->surface)) { return false; }
    }
    uint32_t *image = text ? &c->text : &c->arrow;
    if (!*image) { *image = cursorBuffer(d, text); }
    return *image && btrcWaylandSend(d->wire, pointer, 0, "uuii", serial, c->surface, text ? 10 : 2, text ? 12 : 2) &&
        btrcWaylandSend(d->wire, c->surface, 1, "uii", *image, 0, 0) &&
        btrcWaylandSend(d->wire, c->surface, 2, "iiii", 0, 0, SIZE, SIZE) &&
        btrcWaylandSend(d->wire, c->surface, 6, "");
}

void btrcWaylandCursorClose(BtrcWaylandDisplay *d, BtrcWaylandCursor *c) {
    destroy(d->wire, c->shapeDevice, 0);
    destroy(d->wire, c->surface, 0);
    destroy(d->wire, c->arrow, 0);
    destroy(d->wire, c->text, 0);
    *c = (BtrcWaylandCursor){0};
}
