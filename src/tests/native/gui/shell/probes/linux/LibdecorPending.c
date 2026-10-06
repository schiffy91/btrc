/* Dependency diagnostic, not a replacement event loop or acceptance workaround.
 * Build with libdecor-0 and wayland-client. Exit 1 demonstrates that a pending
 * callback ran but libdecor_dispatch(-1) did not return within three seconds. */
#define _POSIX_C_SOURCE 200809L
#include <libdecor.h>
#include <wayland-client.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* Required calls and checks remain active in release (-DNDEBUG) builds. */
#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "ERROR: %s failed\n", #condition); \
        exit(2); \
    } \
} while (0)

static volatile sig_atomic_t delivered;
static volatile sig_atomic_t phase; /* 0: setup, 1: dispatch, 2: cleanup. */

static void expired(int signal_number) {
    (void)signal_number;
    const char pending[] = "FAIL: callback delivered; libdecor dispatch still blocked\n";
    const char absent[] = "ERROR: callback not delivered\n";
    const char cleanup[] = "ERROR: dispatch returned; cleanup timed out\n";
    int dispatch_blocked = phase == 1 && delivered;
    if (dispatch_blocked) (void)write(STDERR_FILENO, pending, sizeof(pending) - 1);
    else if (phase == 2) (void)write(STDERR_FILENO, cleanup, sizeof(cleanup) - 1);
    else (void)write(STDERR_FILENO, absent, sizeof(absent) - 1);
    _exit(dispatch_blocked ? 1 : 2);
}

static void done(void *data, struct wl_callback *callback, uint32_t serial) {
    (void)data;
    (void)serial;
    delivered = 1;
    wl_callback_destroy(callback);
    puts("sync callback delivered");
    fflush(stdout);
}

static void failed(struct libdecor *context, enum libdecor_error error, const char *message) {
    (void)context;
    fprintf(stderr, "libdecor error %d: %s\n", (int)error, message);
    exit(2);
}

int main(int argc, char **argv) {
    struct sigaction action = {0};
    action.sa_handler = expired;
    REQUIRE(sigemptyset(&action.sa_mask) == 0);
    REQUIRE(sigaction(SIGALRM, &action, NULL) == 0);
    alarm(10); /* Bound connect, context creation and every initial roundtrip. */
    int timeout = argc == 2 ? atoi(argv[1]) : -1;
    REQUIRE(argc <= 2 && (timeout == -1 || timeout == 0));
    struct wl_display *display = wl_display_connect(NULL);
    REQUIRE(display);
    struct libdecor_interface interface = {.error = failed};
    struct libdecor *decor = libdecor_new(display, &interface);
    REQUIRE(decor);
    REQUIRE(wl_display_roundtrip(display) >= 0);
    REQUIRE(libdecor_dispatch(decor, 0) >= 0);
    struct wl_callback *callback = wl_display_sync(display);
    const struct wl_callback_listener listener = {.done = done};
    REQUIRE(wl_callback_add_listener(callback, &listener, NULL) == 0);
    while (wl_display_prepare_read(display) != 0) REQUIRE(wl_display_dispatch_pending(display) >= 0);
    REQUIRE(wl_display_flush(display) >= 0);
    struct pollfd descriptor = {wl_display_get_fd(display), POLLIN, 0};
    REQUIRE(poll(&descriptor, 1, 1000) == 1);
    REQUIRE(wl_display_read_events(display) == 0);
    REQUIRE(!delivered);
    phase = 1;
    alarm(3);
    int count = libdecor_dispatch(decor, timeout);
    phase = 2;
    alarm(3); /* A cleanup stall is an error, not the dispatch reproduction. */
    printf("dispatch returned %d; callback delivered=%d\n", count, (int)delivered);
    libdecor_unref(decor);
    wl_display_disconnect(display);
    alarm(0);
    return delivered && count >= 0 ? 0 : 2;
}
