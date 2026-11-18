/* The probe for a window of the GTK provider: real input, sent through the
 * display server (RealInput.h) to wherever that window is on the screen.
 *
 * Two things the display server will not tell an input tool come from the
 * provider's shim instead (GUI/Linux/Gtk/GtkShim.h, "automation"): where the
 * pointer is in a window's content, which is how the probe learns where that
 * content is on the screen, and whether input it sent has arrived, which is
 * how it knows when to return. Neither delivers input. */
#include "GtkProbe.h"
#include "RealInput.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

int btrcGtkAutomationDisplay(void) __attribute__((weak));
unsigned long btrcGtkAutomationSerial(void) __attribute__((weak));
int btrcGtkAutomationAwait(unsigned long serial, int timeoutMilliseconds) __attribute__((weak));
int btrcGtkAutomationPointer(unsigned int window, double *x, double *y) __attribute__((weak));

enum { ARRIVAL_MILLISECONDS = 500, SEARCH_MILLISECONDS = 60, APPEARANCE_ATTEMPTS = 60, DISPLAY_X11 = 2 };

static const RealInput *input;
/* The screen position of the located window's content origin. */
static struct { unsigned int window; double x, y; } content;
static unsigned int active;

/* Real input moves the session's one pointer, so the session has to be one
 * made for tests: tools/ui/headless-session.sh says so with this variable,
 * and a dedicated test host sets it by hand. */
static const RealInput *realInput(void) {
    static bool tried;
    if (!tried) {
        tried = true;
        const char *allowed = getenv("BTRC_UI_PRIVATE_SESSION");
        if (allowed && strcmp(allowed, "1") == 0 && btrcGtkAutomationDisplay) {
            input = btrcGtkAutomationDisplay() == DISPLAY_X11 ? realInputX11() : realInputWayland();
        }
    }
    return input;
}

static void arrived(unsigned long serial, int milliseconds) { btrcGtkAutomationAwait(serial, milliseconds); }

static void typed(void) { arrived(btrcGtkAutomationSerial(), SEARCH_MILLISECONDS); }

/* Move the pointer to a screen position; true when it is then over the
 * window's content, at the content position returned. */
static bool pointAt(unsigned int window, double screenX, double screenY, int milliseconds, double *x, double *y) {
    unsigned long serial = btrcGtkAutomationSerial();
    if (!input->move(screenX, screenY)) { return false; }
    arrived(serial, milliseconds);
    return btrcGtkAutomationPointer(window, x, y) != 0;
}

static bool learn(unsigned int window, double screenX, double screenY, int milliseconds) {
    double x = 0.0;
    double y = 0.0;
    if (!pointAt(window, screenX, screenY, milliseconds, &x, &y)) { return false; }
    content.window = window;
    content.x = screenX - x;
    content.y = screenY - y;
    return true;
}

/* Find the window's content on the screen by pointing at it: down the
 * window's left side where the display server says where the window is, at
 * the middle of the screen where a compositor puts a new window, and then
 * everywhere. */
static bool locate(unsigned int window, const char *title) {
    double width = 0.0;
    double height = 0.0;
    double left = 0.0;
    double top = 0.0;
    if (content.window == window) { return true; }
    input->extent(&width, &height);
    if (input->origin(title, &left, &top)) {
        for (double down = 8.0; down < 320.0; down += 12.0) { if (learn(window, left + 32.0, top + down, ARRIVAL_MILLISECONDS)) { return true; } }
    }
    if (learn(window, width / 2.0, height / 2.0, ARRIVAL_MILLISECONDS)) { return true; }
    for (double y = 20.0; y < height; y += 40.0) {
        for (double x = 20.0; x < width; x += 40.0) { if (learn(window, x, y, SEARCH_MILLISECONDS)) { return true; } }
    }
    return false;
}

/* Raise the window and give it the keyboard. A window that was only just
 * shown is not on the screen yet: GTK and the display server still have to
 * agree on it, so GTK is let run until the display server knows the window. */
static bool activate(unsigned int window, const char *title) {
    if (active == window) { return true; }
    for (int attempt = 0; attempt < APPEARANCE_ATTEMPTS; attempt++) {
        unsigned long serial = btrcGtkAutomationSerial();
        bool known = input->activate(title);
        arrived(serial, SEARCH_MILLISECONDS);
        if (known) { active = window; return true; }
    }
    return false;
}

/* Put the pointer on a content position. A position outside the content is
 * sent as asked: nothing will report the pointer there. */
static bool pointer(unsigned int window, const char *title, double x, double y) {
    if (!realInput() || !activate(window, title) || !locate(window, title)) { return false; }
    for (int attempt = 0; attempt < 2; attempt++) {
        double seenX = 0.0;
        double seenY = 0.0;
        if (!pointAt(window, content.x + x, content.y + y, ARRIVAL_MILLISECONDS, &seenX, &seenY)) { return true; }
        if (fabs(seenX - x) < 1.0 && fabs(seenY - y) < 1.0) { return true; }
        /* The window moved since it was located. */
        content.window = 0;
        if (!locate(window, title)) { return false; }
    }
    return false;
}

int gtkProbeMove(unsigned int window, const char *title, double x, double y) { return pointer(window, title, x, y) ? 1 : 0; }

int gtkProbeButton(unsigned int window, const char *title, double x, double y, int down) {
    if (!pointer(window, title, x, y)) { return 0; }
    unsigned long serial = btrcGtkAutomationSerial();
    if (!input->button(down != 0)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int gtkProbeWheel(unsigned int window, const char *title, double x, double y, double deltaX, double deltaY) {
    if (!pointer(window, title, x, y)) { return 0; }
    unsigned long serial = btrcGtkAutomationSerial();
    if (!input->wheel(deltaX, deltaY)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int gtkProbeKey(unsigned int window, const char *title, int key) {
    if (!realInput() || !activate(window, title)) { return 0; }
    unsigned long serial = btrcGtkAutomationSerial();
    if (!input->key(key)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int gtkProbeText(unsigned int window, const char *title, const char *text) {
    if (!realInput() || !activate(window, title)) { return 0; }
    unsigned long serial = btrcGtkAutomationSerial();
    if (!input->text(text, typed)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int gtkProbeClose(unsigned int window, const char *title) {
    if (!realInput() || !activate(window, title)) { return 0; }
    unsigned long serial = btrcGtkAutomationSerial();
    if (!input->close(title)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}
