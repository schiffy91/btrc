/* Real input on Wayland: a wlroots compositor's virtual pointer and virtual
 * keyboard, and its foreign-toplevel list for the window manager's part
 * (raise, close). The probe is a second client on its own connection, as any
 * input tool is; the window it drives never sees where the input came from. */
/* memfd_create and open_memstream; the suite's own build already defines it. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "../shim/RealInput.h"
#include "../ConformanceProbe.h"
#include "wayland/wlr-virtual-pointer-unstable-v1-client-protocol.h"
#include "wayland/virtual-keyboard-unstable-v1-client-protocol.h"
#include "wayland/wlr-foreign-toplevel-management-unstable-v1-client-protocol.h"
#include <wayland-client.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

enum { KEYMAP_CAPACITY = 240, TOPLEVEL_CAPACITY = 64, CONTROL_MASK = 4, BUTTON_LEFT = 0x110 };
/* A keymap slot holds a Unicode scalar value, or with this bit a named key. */
#define NAMED_KEY 0x80000000u

typedef struct Toplevel {
    struct zwlr_foreign_toplevel_handle_v1 *handle;
    char title[256];
} Toplevel;

static struct {
    struct wl_display *display;
    struct wl_seat *seat;
    struct wl_output *output;
    struct zwlr_virtual_pointer_manager_v1 *pointers;
    struct zwp_virtual_keyboard_manager_v1 *keyboards;
    struct zwlr_foreign_toplevel_manager_v1 *toplevels;
    struct zwlr_virtual_pointer_v1 *pointer;
    struct zwp_virtual_keyboard_v1 *keyboard;
    int32_t width, height;
    Toplevel windows[TOPLEVEL_CAPACITY];
    /* Slot n of the keymap is evdev key n + 1; the first slots are fixed. */
    uint32_t keysyms[KEYMAP_CAPACITY];
    int keysymCount;
} wl;

static uint32_t now(void) {
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return (uint32_t)(time.tv_sec * 1000 + time.tv_nsec / 1000000);
}

static void outputGeometry(void *data, struct wl_output *output, int32_t x, int32_t y, int32_t physicalWidth, int32_t physicalHeight, int32_t subpixel, const char *make, const char *model, int32_t transform) {
    (void)data; (void)output; (void)x; (void)y; (void)physicalWidth; (void)physicalHeight; (void)subpixel; (void)make; (void)model; (void)transform;
}

static void outputMode(void *data, struct wl_output *output, uint32_t flags, int32_t width, int32_t height, int32_t refresh) {
    (void)data; (void)output; (void)refresh;
    if (flags & WL_OUTPUT_MODE_CURRENT) { wl.width = width; wl.height = height; }
}

static void outputDone(void *data, struct wl_output *output) { (void)data; (void)output; }

static void outputScale(void *data, struct wl_output *output, int32_t factor) { (void)data; (void)output; (void)factor; }

static const struct wl_output_listener outputListener = {.geometry = outputGeometry, .mode = outputMode, .done = outputDone, .scale = outputScale};

static Toplevel *toplevelOf(struct zwlr_foreign_toplevel_handle_v1 *handle) {
    for (int index = 0; index < TOPLEVEL_CAPACITY; index++) { if (wl.windows[index].handle == handle) { return &wl.windows[index]; } }
    return NULL;
}

static void handleTitle(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle, const char *title) {
    (void)data;
    Toplevel *window = toplevelOf(handle);
    if (window) { snprintf(window->title, sizeof window->title, "%s", title); }
}

static void handleAppId(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle, const char *appId) { (void)data; (void)handle; (void)appId; }

static void handleOutput(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle, struct wl_output *output) { (void)data; (void)handle; (void)output; }

static void handleState(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle, struct wl_array *state) { (void)data; (void)handle; (void)state; }

static void handleDone(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle) { (void)data; (void)handle; }

static void handleClosed(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle) {
    (void)data;
    Toplevel *window = toplevelOf(handle);
    if (window) { window->handle = NULL; window->title[0] = '\0'; }
    zwlr_foreign_toplevel_handle_v1_destroy(handle);
}

static void handleParent(void *data, struct zwlr_foreign_toplevel_handle_v1 *handle, struct zwlr_foreign_toplevel_handle_v1 *parent) { (void)data; (void)handle; (void)parent; }

static const struct zwlr_foreign_toplevel_handle_v1_listener handleListener = {
    .title = handleTitle, .app_id = handleAppId, .output_enter = handleOutput, .output_leave = handleOutput,
    .state = handleState, .done = handleDone, .closed = handleClosed, .parent = handleParent,
};

static void managerToplevel(void *data, struct zwlr_foreign_toplevel_manager_v1 *manager, struct zwlr_foreign_toplevel_handle_v1 *handle) {
    (void)data; (void)manager;
    Toplevel *slot = toplevelOf(NULL);
    if (slot) { slot->handle = handle; slot->title[0] = '\0'; }
    zwlr_foreign_toplevel_handle_v1_add_listener(handle, &handleListener, NULL);
}

static void managerFinished(void *data, struct zwlr_foreign_toplevel_manager_v1 *manager) { (void)data; (void)manager; }

static const struct zwlr_foreign_toplevel_manager_v1_listener managerListener = {.toplevel = managerToplevel, .finished = managerFinished};

static void registryGlobal(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version) {
    (void)data; (void)version;
    if (strcmp(interface, wl_seat_interface.name) == 0 && !wl.seat) { wl.seat = wl_registry_bind(registry, name, &wl_seat_interface, 1); }
    else if (strcmp(interface, wl_output_interface.name) == 0 && !wl.output) {
        wl.output = wl_registry_bind(registry, name, &wl_output_interface, 2);
        wl_output_add_listener(wl.output, &outputListener, NULL);
    } else if (strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name) == 0) { wl.pointers = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1); }
    else if (strcmp(interface, zwp_virtual_keyboard_manager_v1_interface.name) == 0) { wl.keyboards = wl_registry_bind(registry, name, &zwp_virtual_keyboard_manager_v1_interface, 1); }
    else if (strcmp(interface, zwlr_foreign_toplevel_manager_v1_interface.name) == 0) {
        wl.toplevels = wl_registry_bind(registry, name, &zwlr_foreign_toplevel_manager_v1_interface, 1);
        zwlr_foreign_toplevel_manager_v1_add_listener(wl.toplevels, &managerListener, NULL);
    }
}

static void registryRemove(void *data, struct wl_registry *registry, uint32_t name) { (void)data; (void)registry; (void)name; }

static const struct wl_registry_listener registryListener = {registryGlobal, registryRemove};

static bool roundtrip(void) { return wl_display_roundtrip(wl.display) >= 0; }

static const char *keysymName(uint32_t keysym, char *buffer, size_t size) {
    switch (keysym) {
    case NAMED_KEY | 0xff0d: return "Return";
    case NAMED_KEY | 0xff1b: return "Escape";
    case NAMED_KEY | 0xff09: return "Tab";
    case NAMED_KEY | 0xff51: return "Left";
    case NAMED_KEY | 0xff53: return "Right";
    case NAMED_KEY | 0xff52: return "Up";
    case NAMED_KEY | 0xff54: return "Down";
    case NAMED_KEY | 0xff08: return "BackSpace";
    default: snprintf(buffer, size, "U%04X", keysym & 0xffffffu); return buffer;
    }
}

/* The keyboard's layout is whatever the test needs typed: every key yields
 * one symbol at every level, so no modifier is ever needed to reach it. */
static bool uploadKeymap(void) {
    char *text = NULL;
    size_t size = 0;
    FILE *out = open_memstream(&text, &size);
    if (!out) { return false; }
    fprintf(out, "xkb_keymap {\nxkb_keycodes \"probe\" {\nminimum = 8;\nmaximum = %d;\n", wl.keysymCount + 8);
    for (int index = 0; index < wl.keysymCount; index++) { fprintf(out, "<K%d> = %d;\n", index + 1, index + 9); }
    fprintf(out, "};\nxkb_types \"probe\" { include \"complete\" };\nxkb_compatibility \"probe\" { include \"complete\" };\nxkb_symbols \"probe\" {\n");
    for (int index = 0; index < wl.keysymCount; index++) {
        char buffer[16];
        fprintf(out, "key <K%d> {[%s]};\n", index + 1, keysymName(wl.keysyms[index], buffer, sizeof buffer));
    }
    fprintf(out, "};\n};\n");
    fclose(out);
    int fd = memfd_create("probe-keymap", MFD_CLOEXEC);
    bool written = fd >= 0 && write(fd, text, size + 1) == (ssize_t)(size + 1);
    if (written) { zwp_virtual_keyboard_v1_keymap(wl.keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, (uint32_t)(size + 1)); }
    if (fd >= 0) { close(fd); }
    free(text);
    return written && roundtrip();
}

/* The evdev code of the key that types this symbol, adding one when new. */
static int keyFor(uint32_t keysym) {
    for (int index = 0; index < wl.keysymCount; index++) { if (wl.keysyms[index] == keysym) { return index + 1; } }
    if (wl.keysymCount == KEYMAP_CAPACITY) { return 0; }
    wl.keysyms[wl.keysymCount++] = keysym;
    return uploadKeymap() ? wl.keysymCount : 0;
}

static bool tap(uint32_t keysym, uint32_t modifiers) {
    int key = keyFor(keysym);
    if (!key) { return false; }
    if (modifiers) { zwp_virtual_keyboard_v1_modifiers(wl.keyboard, modifiers, 0, 0, 0); }
    zwp_virtual_keyboard_v1_key(wl.keyboard, now(), (uint32_t)key, WL_KEYBOARD_KEY_STATE_PRESSED);
    zwp_virtual_keyboard_v1_key(wl.keyboard, now(), (uint32_t)key, WL_KEYBOARD_KEY_STATE_RELEASED);
    if (modifiers) { zwp_virtual_keyboard_v1_modifiers(wl.keyboard, 0, 0, 0, 0); }
    return roundtrip();
}

/* A held key, unlike a tap, lets the client act on the compositor's repeat
 * interval. Used by the native Wayland keyboard qualification. */
bool realInputWaylandHoldReturn(void) {
    int key = keyFor(NAMED_KEY | 0xff0d);
    if (!key) { return false; }
    zwp_virtual_keyboard_v1_key(wl.keyboard, now(), (uint32_t)key, WL_KEYBOARD_KEY_STATE_PRESSED);
    if (!roundtrip()) { return false; }
    struct timespec hold = {.tv_sec = 2};
    nanosleep(&hold, NULL);
    zwp_virtual_keyboard_v1_key(wl.keyboard, now(), (uint32_t)key, WL_KEYBOARD_KEY_STATE_RELEASED);
    return roundtrip();
}

static bool waylandMove(double x, double y) {
    zwlr_virtual_pointer_v1_motion_absolute(wl.pointer, now(), (uint32_t)(x < 0 ? 0 : x), (uint32_t)(y < 0 ? 0 : y), (uint32_t)wl.width, (uint32_t)wl.height);
    zwlr_virtual_pointer_v1_frame(wl.pointer);
    return roundtrip();
}

static bool waylandButton(bool down) {
    zwlr_virtual_pointer_v1_button(wl.pointer, now(), BUTTON_LEFT, down ? WL_POINTER_BUTTON_STATE_PRESSED : WL_POINTER_BUTTON_STATE_RELEASED);
    zwlr_virtual_pointer_v1_frame(wl.pointer);
    return roundtrip();
}

static void axis(uint32_t which, double notches) {
    if (notches == 0.0) { return; }
    zwlr_virtual_pointer_v1_axis_source(wl.pointer, WL_POINTER_AXIS_SOURCE_WHEEL);
    zwlr_virtual_pointer_v1_axis_discrete(wl.pointer, now(), which, wl_fixed_from_double(notches * 15.0), (int32_t)notches);
}

/* A wheel turned away from the user scrolls up: Wayland's axis runs the other way. */
static bool waylandWheel(double deltaX, double deltaY) {
    axis(WL_POINTER_AXIS_HORIZONTAL_SCROLL, deltaX);
    axis(WL_POINTER_AXIS_VERTICAL_SCROLL, -deltaY);
    zwlr_virtual_pointer_v1_frame(wl.pointer);
    return roundtrip();
}

static bool waylandKey(int key) {
    switch (key) {
    case CONFORMANCE_KEY_RETURN: return tap(NAMED_KEY | 0xff0d, 0);
    case CONFORMANCE_KEY_ESCAPE: return tap(NAMED_KEY | 0xff1b, 0);
    case CONFORMANCE_KEY_TAB: return tap(NAMED_KEY | 0xff09, 0);
    case CONFORMANCE_KEY_LEFT: return tap(NAMED_KEY | 0xff51, 0);
    case CONFORMANCE_KEY_RIGHT: return tap(NAMED_KEY | 0xff53, 0);
    case CONFORMANCE_KEY_UP: return tap(NAMED_KEY | 0xff52, 0);
    case CONFORMANCE_KEY_DOWN: return tap(NAMED_KEY | 0xff54, 0);
    case CONFORMANCE_KEY_BACKSPACE: return tap(NAMED_KEY | 0xff08, 0);
    case CONFORMANCE_KEY_SELECT_ALL: return tap('a', CONTROL_MASK);
    default: return false;
    }
}

/* One Unicode scalar value from UTF-8; zero ends the text or refuses it. */
static uint32_t nextScalar(const unsigned char **cursor) {
    const unsigned char *text = *cursor;
    uint32_t first = text[0];
    int more = first < 0x80 ? 0 : (first >> 5) == 0x6 ? 1 : (first >> 4) == 0xe ? 2 : (first >> 3) == 0x1e ? 3 : -1;
    if (first == 0 || more < 0) { return 0; }
    uint32_t value = more == 0 ? first : first & (0x3fu >> more);
    for (int index = 1; index <= more; index++) {
        if ((text[index] & 0xc0) != 0x80) { return 0; }
        value = (value << 6) | (text[index] & 0x3fu);
    }
    *cursor = text + more + 1;
    return value;
}

static bool waylandText(const char *text, void (*typed)(void)) {
    const unsigned char *cursor = (const unsigned char *)text;
    while (*cursor) {
        uint32_t scalar = nextScalar(&cursor);
        if (!scalar || !tap(scalar, 0)) { return false; }
        typed();
    }
    return true;
}

static Toplevel *named(const char *title) {
    roundtrip();
    for (int index = 0; index < TOPLEVEL_CAPACITY; index++) {
        if (wl.windows[index].handle && strcmp(wl.windows[index].title, title) == 0) { return &wl.windows[index]; }
    }
    return NULL;
}

static bool waylandActivate(const char *title) {
    Toplevel *window = named(title);
    if (!window) { return false; }
    zwlr_foreign_toplevel_handle_v1_activate(window->handle, wl.seat);
    return roundtrip();
}

static bool waylandClose(const char *title) {
    Toplevel *window = named(title);
    if (!window) { return false; }
    zwlr_foreign_toplevel_handle_v1_close(window->handle);
    return roundtrip();
}

/* A Wayland client is never told where a window is. */
static bool waylandOrigin(const char *title, double *x, double *y) { (void)title; (void)x; (void)y; return false; }

static void waylandExtent(double *width, double *height) { *width = wl.width; *height = wl.height; }

/* A wlroots compositor gives a window the size it asks for. */
static bool waylandFillsScreen(void) { return false; }

static const RealInput waylandInput = {
    .move = waylandMove, .button = waylandButton, .wheel = waylandWheel, .key = waylandKey, .text = waylandText,
    .activate = waylandActivate, .close = waylandClose, .origin = waylandOrigin, .extent = waylandExtent,
    .fillsScreen = waylandFillsScreen,
};

const RealInput *realInputWayland(void) {
    if (wl.pointer) { return &waylandInput; }
    if (wl.display) { return NULL; }
    wl.display = wl_display_connect(NULL);
    if (!wl.display) { return NULL; }
    struct wl_registry *registry = wl_display_get_registry(wl.display);
    wl_registry_add_listener(registry, &registryListener, NULL);
    /* Once for the globals, once for the output's mode and the open windows. */
    roundtrip();
    roundtrip();
    if (!wl.seat || !wl.output || !wl.pointers || !wl.keyboards || !wl.toplevels || wl.width <= 0) { return NULL; }
    wl.pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(wl.pointers, wl.seat);
    wl.keyboard = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(wl.keyboards, wl.seat);
    if (!keyFor('a')) { return NULL; }
    return &waylandInput;
}
