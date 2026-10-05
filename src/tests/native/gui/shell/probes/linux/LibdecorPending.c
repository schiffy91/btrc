/* Dependency diagnostic, not a replacement event loop or acceptance workaround.
 * Build with libdecor-0 and wayland-client. Exit 1 demonstrates that a pending
 * callback ran but libdecor_dispatch(-1) did not return within three seconds. */
#define _POSIX_C_SOURCE 200809L
#include <libdecor.h>
#include <wayland-client.h>
#include <assert.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static volatile sig_atomic_t delivered;

static void expired(int signal_number) {
    (void)signal_number;
    const char pending[] = "FAIL: callback delivered; libdecor dispatch still blocked\n";
    const char absent[] = "ERROR: callback not delivered\n";
    if (delivered) (void)write(STDERR_FILENO, pending, sizeof(pending) - 1);
    else (void)write(STDERR_FILENO, absent, sizeof(absent) - 1);
    _exit(delivered ? 1 : 2);
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
    int timeout = argc == 2 ? atoi(argv[1]) : -1;
    assert(argc <= 2 && (timeout == -1 || timeout == 0));
    struct wl_display *display = wl_display_connect(NULL);
    assert(display);
    struct libdecor_interface interface = {.error = failed};
    struct libdecor *decor = libdecor_new(display, &interface);
    assert(decor);
    assert(wl_display_roundtrip(display) >= 0);
    assert(libdecor_dispatch(decor, 0) >= 0);
    struct wl_callback *callback = wl_display_sync(display);
    const struct wl_callback_listener listener = {.done = done};
    assert(wl_callback_add_listener(callback, &listener, NULL) == 0);
    while (wl_display_prepare_read(display) != 0) assert(wl_display_dispatch_pending(display) >= 0);
    assert(wl_display_flush(display) >= 0);
    struct pollfd descriptor = {wl_display_get_fd(display), POLLIN, 0};
    assert(poll(&descriptor, 1, 1000) == 1);
    assert(wl_display_read_events(display) == 0);
    assert(!delivered);
    struct sigaction action = {0};
    action.sa_handler = expired;
    assert(sigemptyset(&action.sa_mask) == 0);
    assert(sigaction(SIGALRM, &action, NULL) == 0);
    alarm(3);
    int count = libdecor_dispatch(decor, timeout);
    alarm(0);
    printf("dispatch returned %d; callback delivered=%d\n", count, (int)delivered);
    libdecor_unref(decor);
    wl_display_disconnect(display);
    return delivered && count >= 0 ? 0 : 2;
}
