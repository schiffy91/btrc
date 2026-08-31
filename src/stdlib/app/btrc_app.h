/*
 * btrc application runtime -- one process-global event loop and window.
 *
 * The public ABI uses generation-checked integer capabilities. Native window
 * handles are deliberately absent; platform renderers attach through the
 * private std_app_surface_internal.h boundary. Destructive operations also
 * require the one-time owner receipt returned beside each capability.
 */
#ifndef BTRC_APP_H
#define BTRC_APP_H

#include <stdint.h>

/* BTRC's `unsigned long long` is the hosted capability ABI spelling.  Keep
 * the native declarations byte-for-byte compatible on platforms where
 * uint64_t is instead a typedef of unsigned long (notably LP64 Linux). */
_Static_assert(sizeof(unsigned long long) == sizeof(uint64_t),
    "std.app capabilities require a 64-bit unsigned long long");

#ifdef BTRC_GUI_LEGACY_WINDOW_API
#error "std.app cannot be composed with the legacy std.gui GuiWindow backend"
#endif
#define BTRC_APP_WINDOW_API 1

enum {
    BTRC_APP_ERROR_NONE = 0,
    BTRC_APP_ERROR_INVALID_ARGUMENT = 1,
    BTRC_APP_ERROR_NOT_MAIN_THREAD = 2,
    BTRC_APP_ERROR_ALREADY_RUNNING = 3,
    BTRC_APP_ERROR_BACKEND_UNAVAILABLE = 4,
    BTRC_APP_ERROR_NOT_OPEN = 5,
    BTRC_APP_ERROR_WINDOW_ALREADY_OPEN = 6,
    BTRC_APP_ERROR_WINDOW_CREATE_FAILED = 7,
    BTRC_APP_ERROR_EVENT_QUEUE_OVERFLOW = 8,
    BTRC_APP_ERROR_RESOURCE_BUSY = 9,
    BTRC_APP_ERROR_STALE_SURFACE = 10,
    BTRC_APP_ERROR_SURFACE_ALREADY_CREATED = 11,
    BTRC_APP_ERROR_CLOSED = 12,
    BTRC_APP_ERROR_SURFACE_ALREADY_ATTACHED = 13,
    BTRC_APP_ERROR_INTERNAL = 14,
};

enum {
    BTRC_APP_EVENT_IDLE = 0,
    BTRC_APP_EVENT_POINTER = 1,
    BTRC_APP_EVENT_KEYBOARD = 2,
    BTRC_APP_EVENT_TEXT = 3,
    BTRC_APP_EVENT_RESIZED = 4,
    BTRC_APP_EVENT_DPI_CHANGED = 5,
    BTRC_APP_EVENT_CLOSE_REQUESTED = 6,
    BTRC_APP_EVENT_CLOSED = 7,
    BTRC_APP_EVENT_FAILED = 8,
    BTRC_APP_EVENT_SCROLLED = 9,
};

enum {
    BTRC_APP_POINTER_MOVED = 0,
    BTRC_APP_POINTER_PRESSED = 1,
    BTRC_APP_POINTER_RELEASED = 2,
};

enum {
    BTRC_APP_BUTTON_NONE = 0,
    BTRC_APP_BUTTON_PRIMARY = 1,
    BTRC_APP_BUTTON_SECONDARY = 2,
    BTRC_APP_BUTTON_MIDDLE = 3,
    BTRC_APP_BUTTON_OTHER = 4,
};

enum {
    BTRC_APP_KEY_PRESSED = 0,
    BTRC_APP_KEY_REPEATED = 1,
    BTRC_APP_KEY_RELEASED = 2,
};

enum {
    BTRC_APP_KEY_UNKNOWN = 0,
    BTRC_APP_KEY_ESCAPE = 1,
    BTRC_APP_KEY_ENTER = 2,
    BTRC_APP_KEY_SPACE = 3,
    BTRC_APP_KEY_LEFT = 4,
    BTRC_APP_KEY_RIGHT = 5,
    BTRC_APP_KEY_UP = 6,
    BTRC_APP_KEY_DOWN = 7,
    BTRC_APP_KEY_TAB = 8,
    BTRC_APP_KEY_BACKSPACE = 9,
    BTRC_APP_KEY_A = 10,
    BTRC_APP_KEY_D = 11,
    BTRC_APP_KEY_S = 12,
    BTRC_APP_KEY_W = 13,
    BTRC_APP_KEY_LEFT_SHIFT = 14,
    BTRC_APP_KEY_RIGHT_SHIFT = 15,
};

enum {
    BTRC_APP_MOD_SHIFT = 1,
    BTRC_APP_MOD_CONTROL = 2,
    BTRC_APP_MOD_ALT = 4,
    BTRC_APP_MOD_COMMAND = 8,
};

unsigned long long std_app_create(unsigned long long* owner_receipt_out);
int std_app_error_code(unsigned long long application);
char* std_app_error_message(unsigned long long application);

unsigned long long std_app_window_open(
    unsigned long long application, char* title, int width, int height,
    unsigned long long* owner_receipt_out);
int std_app_window_close(
    unsigned long long window, unsigned long long owner_receipt);

unsigned long long std_app_surface_create(
    unsigned long long window, unsigned long long* owner_receipt_out);
unsigned long long std_app_surface_generation(unsigned long long surface);
int std_app_surface_release(
    unsigned long long surface, unsigned long long owner_receipt);
void std_app_surface_finalize(
    unsigned long long surface, unsigned long long owner_receipt);

int std_app_poll(unsigned long long application);
int std_app_event_pointer_action(unsigned long long application);
int std_app_event_pointer_button(unsigned long long application);
float std_app_event_pointer_x(unsigned long long application);
float std_app_event_pointer_y(unsigned long long application);
float std_app_event_scroll_x(unsigned long long application);
float std_app_event_scroll_y(unsigned long long application);
int std_app_event_key_action(unsigned long long application);
int std_app_event_key(unsigned long long application);
int std_app_event_modifiers(unsigned long long application);
char* std_app_event_text(unsigned long long application);
int std_app_event_logical_width(unsigned long long application);
int std_app_event_logical_height(unsigned long long application);
int std_app_event_framebuffer_width(unsigned long long application);
int std_app_event_framebuffer_height(unsigned long long application);
float std_app_event_scale_x(unsigned long long application);
float std_app_event_scale_y(unsigned long long application);

int std_app_window_logical_width(unsigned long long window);
int std_app_window_logical_height(unsigned long long window);
int std_app_window_framebuffer_width(unsigned long long window);
int std_app_window_framebuffer_height(unsigned long long window);
float std_app_window_scale_x(unsigned long long window);
float std_app_window_scale_y(unsigned long long window);

int std_app_close(
    unsigned long long application, unsigned long long owner_receipt);
void std_app_window_finalize(
    unsigned long long window, unsigned long long owner_receipt);
void std_app_finalize(
    unsigned long long application, unsigned long long owner_receipt);

#endif
