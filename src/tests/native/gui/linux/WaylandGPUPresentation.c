/* Native window affordances for a real Library.GPU surface-renderer test. */
#include "WaylandGPUPresentation.h"
#include "Platform.h"
#include "../../../../stdlib/GUI/Shim/ShimSurface.h"
#include <stdio.h>
#include <string.h>

static BtrcShimWindow *window;
static BtrcShimControl *fill;

bool openSoftwareWindow(void) {
    if (!btrcShimInit()) { return false; }
    window = btrcShimWindowCreate("btrc input and pixels", 160, 100);
    fill = btrcShimFillCreate(1);
    if (!window || !fill) { return false; }
    btrcShimFillSet(fill, 37, 179, 125, 255, 0);
    btrcShimWindowBeginPlacement(window);
    btrcShimWindowPlace(window, fill, 0, 0, 160, 100, 0, 0, 160, 100);
    btrcShimWindowEndPlacement(window);
    if (!btrcShimWindowShow(window)) { return false; }
    long long end = btrcWaylandMilliseconds() + 3000;
    for (;;) {
        BtrcShimEvent event;
        if (btrcWaylandMilliseconds() >= end) { return false; }
        if (btrcShimWaitEvent(&event, 100) && event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) { break; }
    }
    puts("software ready");
    fflush(stdout);
    return getchar() == '\n';
}

WGPUInstance createGPUInstance(void) { return btrcShimCreateInstance(); }

WGPUSurface attachGPUView(WGPUInstance instance) {
    WGPUSurface surface = btrcShimWindowCreateSurface(window, instance);
    if (!surface) { return NULL; }
    btrcShimWindowBeginPlacement(window);
    btrcShimWindowPlace(window, fill, 0, 0, 160, 100, 0, 0, 160, 100);
    btrcShimWindowPlaceHole(window, 40, 25, 80, 50, 0, 0, 160, 100);
    btrcShimWindowEndPlacement(window);
    return surface;
}

bool waitForInput(void) {
    btrcShimWindowStartTextInput(window);
    puts("GPU ready");
    fflush(stdout);
    bool closed = false, clicked = false, entered = false, shortcut = false, acknowledged = false;
    char text[32] = "";
    long long end = btrcWaylandMilliseconds() + 15000;
    while (!closed && btrcWaylandMilliseconds() < end) {
        BtrcShimEvent event;
        if (btrcShimWaitEvent(&event, 100)) {
            if (event.window != btrcShimWindowId(window)) { continue; }
            if (event.type == BTRC_SHIM_EVENT_TEXT_INPUT) {
                if (strlen(text) + strlen(event.text) >= sizeof(text)) { return false; }
                strcat(text, event.text);
            }
            if (event.type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN) {
                clicked = event.button == 1 && event.x >= 40 && event.x < 120 && event.y >= 25 && event.y < 75;
            }
            if (event.type == BTRC_SHIM_EVENT_KEY_DOWN) {
                entered |= event.key == BTRC_SHIM_KEY_RETURN;
                shortcut |= event.key == BTRC_SHIM_KEY_A && (event.modifiers & BTRC_SHIM_MOD_CTRL);
            }
            if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { closed = true; }
            if (!acknowledged && clicked && entered && shortcut && !strcmp(text, "Aé🟢")) {
                acknowledged = true;
                puts("input received");
                fflush(stdout);
            }
        }
    }
    bool passed = closed && clicked && entered && shortcut && !strcmp(text, "Aé🟢");
    if (!passed) {
        fprintf(stderr, "Wayland GPU window input: close=%d click=%d return=%d ctrl-a=%d text='%s' error='%s'\n",
                closed, clicked, entered, shortcut, text, btrcShimError());
    }
    return passed;
}

void closeSoftwareWindow(void) {
    btrcShimControlDestroy(fill);
    btrcShimWindowDestroy(window);
}
