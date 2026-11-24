/* Send physical evdev positions through a compositor-owned virtual keyboard. */
#define _POSIX_C_SOURCE 200809L
#include "../conformance/probes/shim/RealInput.h"
#include "../conformance/probes/ConformanceProbe.h"
#include <assert.h>
#include <fcntl.h>
#include <linux/input-event-codes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static void settle(void) {
    struct timespec pause = {.tv_nsec = 30000000};
    nanosleep(&pause, NULL);
}

static void requireTitle(const RealInput *input, const char *title) {
    for (int i = 0; i < 200; ++i) {
        if (input->activate(title)) { settle(); return; }
        settle();
    }
    fprintf(stderr, "Window manager did not receive title %s\n", title);
    exit(1);
}

static void tap(unsigned code, unsigned depressed, unsigned locked) {
    assert(realInputWaylandKeycode(code, depressed, locked));
    settle();
}

int main(int argc, char **argv) {
    assert(argc == 2 && getenv("BTRC_UI_PRIVATE_SESSION") && !strcmp(getenv("BTRC_UI_PRIVATE_SESSION"), "1"));
    const RealInput *input = realInputWayland();
    assert(input);
    requireTitle(input, "Native BTRC");
    assert(input->key(CONFORMANCE_KEY_TAB));
    settle();
    assert(input->key(CONFORMANCE_KEY_SELECT_ALL));
    settle();
    int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    struct stat st;
    assert(fd >= 0 && fstat(fd, &st) == 0 && st.st_size > 0 && st.st_size < (1 << 20));
    assert(realInputWaylandUseKeymap(fd, (unsigned)st.st_size));
    close(fd);
    tap(KEY_KP2, 0, 16);
    tap(KEY_KPPLUS, 0, 0);
    tap(KEY_KP3, 0, 16);
    tap(KEY_KPDOT, 0, 16);
    tap(KEY_KP0, 0, 16);
    tap(KEY_1, 1 | 128, 0);
    tap(KEY_A, 0, 2);
    tap(KEY_B, 1, 2);
    tap(KEY_TAB, 0, 0);
    tap(KEY_ENTER, 0, 0);
    requireTitle(input, "2+3.0!Ab");
    tap(KEY_TAB, 0, 0);
    tap(KEY_ENTER, 0, 0);
    return 0;
}
