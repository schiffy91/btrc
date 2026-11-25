/* Drive the unchanged src/tests/fixtures/gui/Native.btrc using compositor input and
 * confirm that its Apply title callback reaches the window manager. */
#define _POSIX_C_SOURCE 200809L
#include "../conformance/probes/shim/RealInput.h"
#include "../conformance/probes/ConformanceProbe.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

static void settle(void) {
    struct timespec duration = {.tv_nsec=30000000};
    nanosleep(&duration, NULL);
}
static bool activate(const RealInput *device, const char *title) {
    for (int i = 0; i < 200; ++i) {
        if (device->activate(title)) { settle(); return true; }
        settle();
    }
    return false;
}
static void key(const RealInput *device, int code) {
    assert(device->key(code));
    settle();
}
int main(int argc, char **argv) {
    const char *privateSession = getenv("BTRC_UI_PRIVATE_SESSION");
    assert(privateSession && !strcmp(privateSession, "1"));
    const RealInput *device = realInputWayland();
    assert(device);
    if (argc == 2) {
        bool withMenu = !strcmp(argv[1], "ime-menu");
        if (withMenu || !strcmp(argv[1], "ime")) {
            puts("keyboard ready"); fflush(stdout);
            assert(activate(device, "Native BTRC"));
            key(device, CONFORMANCE_KEY_TAB);
            puts("field focused"); fflush(stdout);
            assert(getchar() == '\n');
            if (withMenu) {
                key(device, CONFORMANCE_KEY_TAB);
                key(device, CONFORMANCE_KEY_RETURN);
                key(device, CONFORMANCE_KEY_DOWN);
                key(device, CONFORMANCE_KEY_RETURN);
            }
            key(device, CONFORMANCE_KEY_TAB);
            key(device, CONFORMANCE_KEY_RETURN);
            assert(activate(device, withMenu ? "Native Wayland / Second" : "Native Wayland"));
            key(device, CONFORMANCE_KEY_TAB);
            key(device, CONFORMANCE_KEY_RETURN);
        } else if (!strcmp(argv[1], "caret")) {
            puts("keyboard ready"); fflush(stdout);
            assert(activate(device, "Native BTRC"));
            key(device, CONFORMANCE_KEY_TAB);
            key(device, CONFORMANCE_KEY_SELECT_ALL);
            assert(device->text("office", settle));
            puts("ligature ready"); fflush(stdout);
            double x, y;
            assert(scanf("%lf %lf", &x, &y) == 2);
            assert(device->move(x, y)); settle();
            assert(device->button(true)); settle();
            assert(device->button(false)); settle();
            assert(device->text("X", settle));
            key(device, CONFORMANCE_KEY_TAB);
            key(device, CONFORMANCE_KEY_RETURN);
            assert(activate(device, "oXffice"));
            key(device, CONFORMANCE_KEY_TAB);
            key(device, CONFORMANCE_KEY_RETURN);
        } else { return 2; }
        return 0;
    }
    assert(activate(device, "Native BTRC"));
    key(device, CONFORMANCE_KEY_TAB);
    key(device, CONFORMANCE_KEY_SELECT_ALL);
    assert(device->text("Renamed in Wayland", settle));
    key(device, CONFORMANCE_KEY_TAB);
    key(device, CONFORMANCE_KEY_RETURN);
    assert(activate(device, "Renamed in Wayland"));
    key(device, CONFORMANCE_KEY_TAB);
    key(device, CONFORMANCE_KEY_RETURN);
    puts("Applied the edited title and activated Quit");
    return 0;
}
