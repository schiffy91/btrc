/* Drive the unchanged examples/gui/Native.btrc using compositor input and
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
        if (!strcmp(argv[1], "ime")) {
            puts("keyboard ready"); fflush(stdout);
            assert(activate(device, "Native BTRC"));
            key(device, CONFORMANCE_KEY_TAB);
            puts("field focused"); fflush(stdout);
            assert(getchar() == '\n');
            key(device, CONFORMANCE_KEY_TAB);
            key(device, CONFORMANCE_KEY_RETURN);
            assert(activate(device, "Native Wayland"));
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
