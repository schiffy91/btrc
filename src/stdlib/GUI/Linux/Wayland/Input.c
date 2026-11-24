#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "Client.h"
#include "Keymap.h"
#include "Cursor.h"
#include "Clipboard.h"
#include "TextInput.h"

#include <linux/input-event-codes.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

struct BtrcWaylandSeat {
    BtrcWaylandDisplay *display;
    BtrcWaylandSeat *next;
    uint32_t name;
    uint32_t object;
    uint32_t version;
    uint32_t pointer;
    uint32_t pointerSerial;
    uint32_t pointerSurface;
    BtrcWaylandCursor cursor;
    BtrcWaylandClipboard clipboard;
    BtrcWaylandTextInput text;
    uint32_t keyboard;
    uint32_t modifiers;
    uint32_t active;
    uint32_t group;
    int repeatDelay;
    int repeatRate;
    uint32_t repeatCode;
    long long nextRepeat;
    BtrcWaylandKeymap *keymap;
    BtrcWaylandWindow *pointerFocus;
    BtrcWaylandWindow *keyboardFocus;
    float x;
    float y;
    float axis[2];
    int discrete[2];
    unsigned source;
    uint32_t clickTime;
    uint32_t clickWindow;
    unsigned clickButton;
    unsigned clicks;
    float clickX;
    float clickY;
};

static bool pointerMessage(BtrcWaylandSeat *s, unsigned type, unsigned button, unsigned clicks, bool down) {
    if (!s->pointerFocus) { return true; }
    BtrcShimEvent event = {.type = type, .window = s->pointerFocus->id,
        .x = s->x, .y = s->y, .button = button, .clicks = clicks, .down = down, .modifiers = s->modifiers};
    if (s->pointerSurface != s->pointerFocus->surface) { return btrcWaylandMenuPointer(s->pointerFocus, s->pointerSurface, &event); }
    return btrcWaylandQueueEvent(s->display, event);
}

static bool emitAxis(BtrcWaylandSeat *s) {
    bool smooth = s->source == 1 || s->source == 2;
    float dx = !smooth && s->discrete[1] ? (float)s->discrete[1] : s->axis[1];
    float dy = !smooth && s->discrete[0] ? (float)s->discrete[0] : s->axis[0];
    s->axis[0] = s->axis[1] = 0;
    s->discrete[0] = s->discrete[1] = 0;
    s->source = 0;
    if (!s->pointerFocus || (dx == 0 && dy == 0)) { return true; }
    BtrcShimEvent event = {.type = BTRC_SHIM_EVENT_MOUSE_WHEEL, .window = s->pointerFocus->id,
        .x = s->x, .y = s->y, .wheelX = dx, .wheelY = -dy, .data1 = smooth, .modifiers = s->modifiers};
    if (s->pointerSurface != s->pointerFocus->surface) { return btrcWaylandMenuPointer(s->pointerFocus, s->pointerSurface, &event); }
    return btrcWaylandQueueEvent(s->display, event);
}

static bool pointerEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *e) {
    (void)object;
    BtrcWaylandSeat *s = owner;
    switch (opcode) {
    case 0:
        s->pointerSerial = btrcWaylandUint(e);
        s->pointerSurface = btrcWaylandUint(e);
        s->pointerFocus = btrcWaylandSurfaceWindow(s->display, s->pointerSurface);
        s->x = btrcWaylandInt(e) / 256.f;
        s->y = btrcWaylandInt(e) / 256.f;
        return pointerMessage(s, BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER, 0, 0, false);
    case 1:
        (void)btrcWaylandUint(e);
        (void)btrcWaylandUint(e);
        if (!pointerMessage(s, BTRC_SHIM_EVENT_WINDOW_MOUSE_LEAVE, 0, 0, false)) { return false; }
        s->pointerFocus = NULL;
        return true;
    case 2:
        (void)btrcWaylandUint(e);
        s->x = btrcWaylandInt(e) / 256.f;
        s->y = btrcWaylandInt(e) / 256.f;
        return pointerMessage(s, BTRC_SHIM_EVENT_MOUSE_MOTION, 0, 0, false);
    case 3: {
        uint32_t serial = btrcWaylandUint(e);
        if (!btrcWaylandClipboardSerial(&s->clipboard, serial)) { return false; }
        uint32_t time = btrcWaylandUint(e);
        unsigned code = btrcWaylandUint(e);
        bool down = btrcWaylandUint(e) != 0;
        if (down && s->pointerFocus) { s->pointerFocus->activationSeat = s->object; s->pointerFocus->activationSerial = serial; }
        unsigned button = code == BTN_LEFT ? 1 : code == BTN_MIDDLE ? 2 : code == BTN_RIGHT ? 3 : code == BTN_SIDE ? 4 : code == BTN_EXTRA ? 5 : 0;
        if (down && s->pointerFocus) {
            float dx = s->x - s->clickX;
            float dy = s->y - s->clickY;
            s->clicks = s->clickButton == button && s->clickWindow == s->pointerFocus->id && time - s->clickTime < 250 && dx*dx + dy*dy <= 25 ? s->clicks + 1 : 1;
            s->clickTime = time;
            s->clickWindow = s->pointerFocus->id;
            s->clickX = s->x;
            s->clickY = s->y;
            s->clickButton = button;
        }
        return pointerMessage(s, down ? BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN : BTRC_SHIM_EVENT_MOUSE_BUTTON_UP, button, s->clicks, down);
    }
    case 4: {
        (void)btrcWaylandUint(e);
        unsigned axis = btrcWaylandUint(e);
        float value = btrcWaylandInt(e) / 256.f;
        if (axis < 2) { s->axis[axis] += value; }
        return s->version >= 5 || emitAxis(s);
    }
    case 5: return emitAxis(s);
    case 6: s->source = btrcWaylandUint(e); return true;
    case 7: (void)btrcWaylandUint(e); (void)btrcWaylandUint(e); return true;
    case 8: {
        unsigned axis = btrcWaylandUint(e);
        int value = btrcWaylandInt(e);
        if (axis < 2) { s->discrete[axis] = value; }
        return true;
    }
    default: return false;
    }
}

static bool focus(BtrcWaylandSeat *s, BtrcWaylandWindow *window) {
    if (s->keyboardFocus == window) { return true; }
    if (s->keyboardFocus && !btrcWaylandQueueEvent(s->display, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST, .window = s->keyboardFocus->id})) { return false; }
    s->nextRepeat = 0;
    s->keyboardFocus = window;
    return !window || btrcWaylandQueueEvent(s->display, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED, .window = window->id});
}

static bool sendKey(BtrcWaylandSeat *s, uint32_t code, BtrcWaylandKey key, bool down, bool repeat) {
    unsigned id = s->keyboardFocus->id;
    if (!btrcWaylandQueueEvent(s->display, (BtrcShimEvent){
            .key = key.key, .scancode = key.scancode, .type = down ? BTRC_SHIM_EVENT_KEY_DOWN : BTRC_SHIM_EVENT_KEY_UP,
            .window = id, .down = down, .repeat = repeat, .data1 = (int)code, .modifiers = s->modifiers})) { return false; }
    return !down || !key.text[0] || !s->keyboardFocus->textInput ||
        btrcWaylandQueueEvent(s->display, (BtrcShimEvent){.type = BTRC_SHIM_EVENT_TEXT_INPUT, .window = id, .text = key.text});
}

int btrcWaylandRepeatTimeout(BtrcWaylandDisplay *d, int timeout) {
    long long now = btrcWaylandMilliseconds();
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) {
        if (!s->nextRepeat) { continue; }
        long long left = s->nextRepeat - now;
        if (left <= 0) { return 0; }
        if (timeout < 0 || left < timeout) { timeout = (int)left; }
    }
    return timeout;
}

int btrcWaylandSendRepeats(BtrcWaylandDisplay *d) {
    int sent = 0;
    long long now = btrcWaylandMilliseconds();
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) {
        if (!s->keyboardFocus || !s->nextRepeat || s->nextRepeat > now) { continue; }
        BtrcWaylandKey key = btrcWaylandKey(s->keymap, s->repeatCode, s->active, s->group);
        if (!sendKey(s, s->repeatCode, key, true, true)) { return -1; }
        /* Keep the loop responsive after suspension or an application stall. */
        s->nextRepeat = now + (s->repeatRate > 1000 ? 1 : 1000 / s->repeatRate);
        sent = 1;
    }
    return sent;
}

static bool keyboardEvent(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *e) {
    (void)object;
    BtrcWaylandSeat *s = owner;
    switch (opcode) {
    case 0: {
        uint32_t format = btrcWaylandUint(e);
        int fd = btrcWaylandFd(e);
        uint32_t size = btrcWaylandUint(e);
        if (fd < 0) { return false; }
        s->nextRepeat = 0;
        btrcWaylandKeymapFree(s->keymap);
        s->keymap = format == 1 ? btrcWaylandKeymapRead(fd, size) : NULL;
        close(fd);
        return true;
    }
    case 1: {
        s->clipboard.lostFocus = false;
        if (!btrcWaylandClipboardSerial(&s->clipboard, btrcWaylandUint(e))) { return false; }
        uint32_t surface = btrcWaylandUint(e);
        uint32_t length;
        (void)btrcWaylandArray(e, &length);
        return !(length & 3u) && focus(s, btrcWaylandSurfaceWindow(s->display, surface));
    }
    case 2:
        (void)btrcWaylandUint(e);
        (void)btrcWaylandUint(e);
        s->clipboard.hasSerial = false;
        s->clipboard.lostFocus = true;
        return focus(s, NULL);
    case 3: {
        uint32_t serial = btrcWaylandUint(e);
        if (!btrcWaylandClipboardSerial(&s->clipboard, serial)) { return false; }
        (void)btrcWaylandUint(e);
        unsigned keycode = btrcWaylandUint(e);
        bool down = btrcWaylandUint(e) != 0;
        if (!s->keyboardFocus) { return true; }
        if (down) { s->keyboardFocus->activationSeat = s->object; s->keyboardFocus->activationSerial = serial; }
        BtrcWaylandKey key = btrcWaylandKey(s->keymap, keycode, s->active, s->group);
        if (down && key.repeats && s->repeatRate) {
            s->repeatCode = keycode;
            s->nextRepeat = btrcWaylandMilliseconds() + s->repeatDelay;
        } else if (!down && keycode == s->repeatCode) { s->nextRepeat = 0; }
        return sendKey(s, keycode, key, down, false);
    }
    case 4: {
        (void)btrcWaylandUint(e);
        uint32_t active = btrcWaylandUint(e);
        active |= btrcWaylandUint(e);
        active |= btrcWaylandUint(e);
        s->active = active;
        s->group = btrcWaylandUint(e);
        s->modifiers = (active & 1 ? BTRC_SHIM_MOD_SHIFT : 0) | (active & 4 ? BTRC_SHIM_MOD_CTRL : 0) |
            (active & 8 ? BTRC_SHIM_MOD_ALT : 0) | (active & 64 ? BTRC_SHIM_MOD_GUI : 0);
        s->display->modifiers = s->modifiers;
        return true;
    }
    case 5:
        s->repeatRate = btrcWaylandInt(e);
        s->repeatDelay = btrcWaylandInt(e);
        s->nextRepeat = 0;
        return s->repeatRate >= 0 && s->repeatDelay >= 0;
    default: return false;
    }
}

static void dropDevice(BtrcWaylandSeat *s, uint32_t *device, unsigned opcode) {
    if (*device) {
        if (s->version >= 3) { btrcWaylandSend(s->display->wire, *device, opcode, ""); }
        btrcWaylandRetire(s->display->wire, *device);
        *device = 0;
    }
}

static bool seatEvent(void *owner, uint32_t id, unsigned opcode, BtrcWaylandEvent *event) {
    BtrcWaylandSeat *s = owner;
    if (opcode == 1) { (void)btrcWaylandString(event); return true; }
    if (opcode) { return false; }
    uint32_t capabilities = btrcWaylandUint(event);
    if ((capabilities & 1) && !s->pointer) {
        s->pointer = btrcWaylandObject(event->wire, "wl_pointer", s, pointerEvent, 0);
        if (!s->pointer || !btrcWaylandSend(event->wire, id, 0, "u", s->pointer)) { return false; }
    } else if (!(capabilities & 1)) {
        btrcWaylandCursorClose(s->display, &s->cursor);
        dropDevice(s, &s->pointer, 1);
        s->pointerFocus = NULL;
    }
    if ((capabilities & 2) && !s->keyboard) {
        s->keyboard = btrcWaylandObject(event->wire, "wl_keyboard", s, keyboardEvent, 1u);
        if (!s->keyboard || !btrcWaylandSend(event->wire, id, 1, "u", s->keyboard)) { return false; }
    } else if (!(capabilities & 2)) { dropDevice(s, &s->keyboard, 0); return focus(s, NULL); }
    return true;
}

bool btrcWaylandSeatBind(BtrcWaylandDisplay *d, uint32_t name, uint32_t version) {
    BtrcWaylandSeat *s = calloc(1, sizeof(*s));
    if (!s) { return false; }
    s->display = d;
    s->name = name;
    s->repeatDelay = 600;
    s->repeatRate = 25;
    s->version = version < 7 ? version : 7;
    s->object = btrcWaylandObject(d->wire, "wl_seat", s, seatEvent, 0);
    s->next = d->seats;
    d->seats = s;
    return s->object && btrcWaylandSend(d->wire, d->registry, 0, "usuu", name, "wl_seat", s->version, s->object) &&
        btrcWaylandTextBind(&s->text, d, s->object) && btrcWaylandClipboardBind(&s->clipboard, d, s->object);
}

void btrcWaylandSeatRemove(BtrcWaylandDisplay *d, uint32_t name) {
    BtrcWaylandSeat **where = &d->seats;
    while (*where && (*where)->name != name) { where = &(*where)->next; }
    if (!*where) { return; }
    BtrcWaylandSeat *s = *where;
    *where = s->next;
    for (BtrcWaylandWindow *w = d->windows; w; w = w->next) {
        if (w->activationSeat == s->object) { w->activationSeat = 0; w->activationSerial = 0; }
    }
    btrcWaylandTextClose(&s->text);
    btrcWaylandClipboardClose(&s->clipboard);
    btrcWaylandCursorClose(s->display, &s->cursor);
    dropDevice(s, &s->pointer, 1);
    dropDevice(s, &s->keyboard, 0);
    if (s->version >= 5) { btrcWaylandSend(d->wire, s->object, 3, ""); }
    btrcWaylandRetire(d->wire, s->object);
    btrcWaylandKeymapFree(s->keymap);
    free(s);
}

bool btrcWaylandBindClipboards(BtrcWaylandDisplay *d) {
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) {
        if (!btrcWaylandClipboardBind(&s->clipboard, d, s->object)) { return false; }
    }
    return true;
}

BtrcWaylandClipboard *btrcWaylandActiveClipboard(BtrcWaylandDisplay *d) {
    if (!d || !d->seats) { return NULL; }
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) { if (s->keyboardFocus) { return &s->clipboard; } }
    return &d->seats->clipboard;
}

bool btrcWaylandBindTextInputs(BtrcWaylandDisplay *d) {
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) {
        if (!btrcWaylandTextBind(&s->text, d, s->object)) { return false; }
    }
    return true;
}

void btrcWaylandUpdateTextInputs(BtrcWaylandWindow *w, bool reset) {
    for (BtrcWaylandSeat *s = w->display->seats; s; s = s->next) {
        if (s->text.focus == w && !btrcWaylandTextUpdate(&s->text, reset)) { w->display->failed = true; }
    }
}

void btrcWaylandWindowCursor(BtrcWaylandWindow *w, int kind) {
    if (kind == w->cursor) { return; }
    w->cursor = kind;
    for (BtrcWaylandSeat *s = w->display->seats; s; s = s->next) {
        if (s->pointerFocus == w && !btrcWaylandCursorApply(w->display, &s->cursor, s->pointer, s->pointerSerial, kind)) {
            w->display->failed = true;
        }
    }
}

bool btrcWaylandPointerPosition(BtrcWaylandDisplay *d, uint32_t window, double *x, double *y) {
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) {
        if (s->pointerFocus && s->pointerFocus->id == window) {
            *x = s->x;
            *y = s->y;
            return true;
        }
    }
    return false;
}

void btrcWaylandSeatForget(BtrcWaylandDisplay *d, BtrcWaylandWindow *w) {
    for (BtrcWaylandSeat *s = d->seats; s; s = s->next) {
        if (s->pointerFocus == w) { s->pointerFocus = NULL; }
        btrcWaylandTextForget(&s->text, w);
        if (s->keyboardFocus == w) { s->keyboardFocus = NULL; s->nextRepeat = 0; }
    }
}

void btrcWaylandSeatsClose(BtrcWaylandDisplay *d) {
    while (d->seats) { btrcWaylandSeatRemove(d, d->seats->name); }
}
