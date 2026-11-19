#ifndef BTRC_CONFORMANCE_REAL_INPUT_H
#define BTRC_CONFORMANCE_REAL_INPUT_H
/* Input sent the way a person's devices send it: through the display server,
 * to whatever window is under the pointer or has the keyboard. Positions are
 * the screen's, in pixels from its top left. One backend serves a process:
 * XTest on an X display, a wlroots compositor's virtual pointer and keyboard
 * on Wayland, SendInput on Windows.
 *
 * This moves the session's one pointer. It is only ever opened in a private
 * headless session or on a dedicated test host, never a person's desktop. */
#include <stdbool.h>

typedef struct RealInput RealInput;

struct RealInput {
    bool (*move)(double x, double y);
    bool (*button)(bool down);
    /* Notches: positive deltaY scrolls away from the user. */
    bool (*wheel)(double deltaX, double deltaY);
    /* One key of ConformanceKey, pressed and released. */
    bool (*key)(int key);
    /* Each character of UTF-8 text as its own key press. `typed` is called
     * after every step whose effect must reach the window before the next. */
    bool (*text)(const char *text, void (*typed)(void));
    /* Bring the titled window to the front and give it the keyboard. */
    bool (*activate)(const char *title);
    /* The window manager's close request. */
    bool (*close)(const char *title);
    /* Where the titled window's top left is on the screen, when the display
     * server tells; false when it does not (Wayland). */
    bool (*origin)(const char *title, double *x, double *y);
    /* The screen's size. */
    void (*extent)(double *width, double *height);
    /* Whether the session gives a new window the whole screen, whatever
     * size it asks for. */
    bool (*fillsScreen)(void);
};

/* NULL when the display offers no way to send input. Each exists only where
 * its display does. */
const RealInput *realInputWayland(void);
const RealInput *realInputX11(void);
const RealInput *realInputWin32(void);
#endif
