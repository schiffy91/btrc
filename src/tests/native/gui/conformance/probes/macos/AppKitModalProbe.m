/* The modal probe for the AppKit provider; ../shim/ModalProbe.h.
 *
 * An alert or an open panel runs a modal loop on the main thread, so a helper
 * thread presses the key: a real key event at the HID tap, which the window
 * server gives to whatever window is key, the modal once it is open. It
 * presses again and again until the case says the modal has returned. */
#include "../shim/ModalProbe.h"
#include "../ConformanceProbe.h"
#import <AppKit/AppKit.h>
#include <pthread.h>
#include <stdbool.h>
#include <time.h>

enum { REPEAT_MILLISECONDS = 600, PRESSES = 200 };

static struct { CGKeyCode code; int first; volatile bool done; bool running; } modal;
static pthread_t helper;

static void pauseFor(int milliseconds) {
    struct timespec wait = {milliseconds / 1000, (long)(milliseconds % 1000) * 1000000L};
    nanosleep(&wait, NULL);
}

static void *answer(void *unused) {
    (void)unused;
    for (int press = 0; press < PRESSES && !modal.done; press++) {
        int until = press == 0 ? modal.first : REPEAT_MILLISECONDS;
        for (int waited = 0; waited < until && !modal.done; waited += 20) { pauseFor(20); }
        if (modal.done) { break; }
        for (int down = 1; down >= 0; down--) {
            CGEventRef event = CGEventCreateKeyboardEvent(NULL, modal.code, down != 0);
            if (event) { CGEventPost(kCGHIDEventTap, event); CFRelease(event); }
        }
    }
    return NULL;
}

int modalProbeAnswer(int key, int milliseconds) {
    if (modal.running || !CGPreflightPostEventAccess()) { return 0; }
    if (key == CONFORMANCE_KEY_ESCAPE) { modal.code = 53; }
    else if (key == CONFORMANCE_KEY_RETURN) { modal.code = 36; }
    else { return 0; }
    modal.first = milliseconds;
    modal.done = false;
    modal.running = pthread_create(&helper, NULL, answer, NULL) == 0;
    return modal.running ? 1 : 0;
}

void modalProbeDone(void) {
    if (!modal.running) { return; }
    modal.done = true;
    pthread_join(helper, NULL);
    modal.running = false;
}

int modalProbeHasFolderChooser(void) { return 1; }
