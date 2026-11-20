/* The probe for a window of the shim provider: real input, sent through the
 * display server or the system (RealInput.h) to wherever that window is on
 * the screen.
 *
 * Two things an input tool is not told come from the provider's shim
 * instead (GUI/Shim/Shim.h, "automation"): where the
 * pointer is in a window's content, which is how the probe learns where that
 * content is on the screen, and whether input it sent has arrived, which is
 * how it knows when to return. Neither delivers input. */
#include "ShimProbe.h"
#include "RealInput.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int btrcShimAutomationDisplay(void);
unsigned long btrcShimAutomationSerial(void);
int btrcShimAutomationAwait(unsigned long serial, int timeoutMilliseconds);
int btrcShimAutomationPointer(unsigned int window, double *x, double *y);

enum { ARRIVAL_MILLISECONDS = 500, SEARCH_MILLISECONDS = 60, APPEARANCE_ATTEMPTS = 160, DISPLAY_WAYLAND = 1, DISPLAY_X11 = 2, DISPLAY_WIN32 = 3, DISPLAY_ANDROID = 4 };

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
        if (allowed && strcmp(allowed, "1") == 0) {
#ifdef _WIN32
            input = btrcShimAutomationDisplay() == DISPLAY_WIN32 ? realInputWin32() : NULL;
#elif defined(__ANDROID__)
            input = btrcShimAutomationDisplay() == DISPLAY_ANDROID ? realInputAndroid() : NULL;
#else
            int display = btrcShimAutomationDisplay();
            input = display == DISPLAY_X11 ? realInputX11() : display == DISPLAY_WAYLAND ? realInputWayland() : NULL;
#endif
        }
    }
    return input;
}

/* BTRC_CONFORMANCE_TRACE=1 says on stderr where the probe pointed and what
 * the window saw, for a host that cannot be watched. */
static void trace(const char *what, double askedX, double askedY, double seenX, double seenY) {
    const char *wanted = getenv("BTRC_CONFORMANCE_TRACE");
    if (wanted && strcmp(wanted, "1") == 0) { fprintf(stderr, "probe: %s asked %.1f,%.1f saw %.1f,%.1f content at %.1f,%.1f\n", what, askedX, askedY, seenX, seenY, content.x, content.y); }
}

static void traceCover(double askedX, double askedY, const char *cover) {
    const char *wanted = getenv("BTRC_CONFORMANCE_TRACE");
    if (wanted && strcmp(wanted, "1") == 0) { fprintf(stderr, "probe: covered asked %.1f,%.1f by %s\n", askedX, askedY, cover); }
}

static void arrived(unsigned long serial, int milliseconds) { btrcShimAutomationAwait(serial, milliseconds); }

static void typed(void) { arrived(btrcShimAutomationSerial(), SEARCH_MILLISECONDS); }

/* Move the pointer to a screen position; true when it is then over the
 * window's content, at the content position returned. */
static bool pointAt(unsigned int window, double screenX, double screenY, int milliseconds, double *x, double *y) {
    unsigned long serial = btrcShimAutomationSerial();
    if (!input->move(screenX, screenY)) { return false; }
    arrived(serial, milliseconds);
    return btrcShimAutomationPointer(window, x, y) != 0;
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
        unsigned long serial = btrcShimAutomationSerial();
        bool known = input->activate(title);
        arrived(serial, SEARCH_MILLISECONDS);
        if (known) {
            /* Where the session gives the keyboard in its own time, it has
             * only just arrived: let the toolkit take it before any input. */
            arrived(btrcShimAutomationSerial(), SEARCH_MILLISECONDS);
            arrived(btrcShimAutomationSerial(), SEARCH_MILLISECONDS);
            active = window;
            return true;
        }
    }
    return false;
}

/* Put the pointer on a content position. A position outside the content is
 * sent as asked: nothing will report the pointer there. */
static bool pointer(unsigned int window, const char *title, double x, double y) {
    if (!realInput()) { trace("no real input", x, y, 0.0, 0.0); return false; }
    if (!activate(window, title)) { trace("not activated", x, y, 0.0, 0.0); return false; }
    if (!locate(window, title)) { trace("not located", x, y, 0.0, 0.0); return false; }
    for (int attempt = 0; attempt < 2; attempt++) {
        double seenX = 0.0;
        double seenY = 0.0;
        if (!pointAt(window, content.x + x, content.y + y, ARRIVAL_MILLISECONDS, &seenX, &seenY)) {
            char cover[160] = "";
            if (attempt == 0 && input->covered && input->covered(content.x + x, content.y + y, cover, (int)sizeof cover)) {
                /* Another program's window came up over this one: bring this
                 * one back to the front, as a person would, and point again. */
                traceCover(x, y, cover);
                active = 0;
                if (!activate(window, title)) { trace("not activated", x, y, 0.0, 0.0); return false; }
                continue;
            }
            trace("outside", x, y, 0.0, 0.0);
            return true;
        }
        if (fabs(seenX - x) < 1.0 && fabs(seenY - y) < 1.0) { return true; }
        trace("elsewhere", x, y, seenX, seenY);
        /* The window moved since it was located. */
        content.window = 0;
        if (!locate(window, title)) { return false; }
    }
    return false;
}

int shimProbeMove(unsigned int window, const char *title, double x, double y) { return pointer(window, title, x, y) ? 1 : 0; }

int shimProbeButton(unsigned int window, const char *title, double x, double y, int down) {
    if (!pointer(window, title, x, y)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!input->button(down != 0)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int shimProbeWheel(unsigned int window, const char *title, double x, double y, double deltaX, double deltaY) {
    if (!pointer(window, title, x, y)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!input->wheel(deltaX, deltaY)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int shimProbeKey(unsigned int window, const char *title, int key) {
    if (!realInput() || !activate(window, title)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!input->key(key)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int shimProbeText(unsigned int window, const char *title, const char *text) {
    if (!realInput() || !activate(window, title)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!input->text(text, typed)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

const RealInput *shimProbeInput(void) { return realInput(); }

int shimProbeFillsScreen(void) { return realInput() && input->fillsScreen() ? 1 : 0; }

int shimProbeKeepsScreen(void) { return realInput() && input->keepsScreen && input->keepsScreen() ? 1 : 0; }

int shimProbeClose(unsigned int window, const char *title) {
    if (!realInput() || !activate(window, title)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!input->close(title)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}
