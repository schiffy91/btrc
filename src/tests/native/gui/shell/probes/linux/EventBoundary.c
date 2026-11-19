#include "EventBoundary.h"
#include "GUI/Shim/Shim.h"
#include <webgpu.h>
#include <stdlib.h>
#include <string.h>

/* The provider shim's queue, as its own sources see it (GtkShimPrivate.h). */
bool btrcGtkPush(const BtrcShimEvent *event, const char *text);
int btrcGtkQueued(unsigned int firstType, unsigned int lastType);
void btrcGtkQueueFlush(void);
void btrcGtkQueueFilter(bool (*accept)(const BtrcShimEvent *event));

/* A key this observer queued says so, and carries its ordinal. */
enum { ORDINAL_MARK = 0x45343021 };

static unsigned int target;
static int latest;
static int frames;
static int admitted;
static int rejected;
static bool armed;

/* Observe successful native presentation without changing the result: a
 * frame presented on the surface, or handed to GTK as a picture. */
WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result == WGPUStatus_Success) { frames++; }
    return result;
}

void __real_btrcShimWindowShowPicture(BtrcShimWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight);
void __wrap_btrcShimWindowShowPicture(BtrcShimWindow *window, const unsigned char *pixels, int pixelWidth, int pixelHeight) {
    __real_btrcShimWindowShowPicture(window, pixels, pixelWidth, pixelHeight);
    frames++;
}

int eventBoundaryFrames(void) { return frames; }

/* Link-only observation: delegate every poll unchanged, preserving its result.
 * Delivery callbacks read the ordinal of the key that was last polled. */
int __real_btrcShimPollEvent(BtrcShimEvent *event);
int __wrap_btrcShimPollEvent(BtrcShimEvent *event) {
    int result = __real_btrcShimPollEvent(event);
    bool key = result && event != NULL && (event->type == BTRC_SHIM_EVENT_KEY_DOWN || event->type == BTRC_SHIM_EVENT_KEY_UP);
    latest = key && event->data2 == ORDINAL_MARK ? event->data1 : 0;
    return result;
}

int eventBoundaryLatest(void) { return latest; }

/* After flushing setup traffic, isolate newly submitted target input from
 * what the display server sends in its own time. Admitted test events are
 * not synthesized, reordered, removed or modified by the observer. */
static bool testInput(const BtrcShimEvent *event) {
    bool kind = event->type == BTRC_SHIM_EVENT_KEY_DOWN || event->type == BTRC_SHIM_EVENT_KEY_UP ||
                event->type == BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED || event->type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED;
    return kind && event->window == target;
}

/* The production scheduler and sliced input loop both need their wakes.
 * Refusing those would inject an unrelated native-source failure. */
static bool accepted(const BtrcShimEvent *event) { return event->type == BTRC_SHIM_EVENT_USER || testInput(event); }

static void push(const BtrcShimEvent *event, const char *text) {
    bool relevant = armed && testInput(event);
    bool result = btrcGtkPush(event, text);
    if (relevant) { if (result) { admitted++; } else { rejected++; } }
}

int eventBoundaryAccepted(void) { return admitted; }
int eventBoundaryRejected(void) { return rejected; }

void eventBoundaryArm(unsigned int window) {
    target = window;
    admitted = rejected = 0;
    armed = true;
    btrcGtkQueueFlush();
    btrcGtkQueueFilter(accepted);
}

void eventBoundaryKey(unsigned int window, int ordinal, int down) {
    static const unsigned int scancodes[4] = {BTRC_SHIM_SCANCODE_A, BTRC_SHIM_SCANCODE_D, BTRC_SHIM_SCANCODE_S, BTRC_SHIM_SCANCODE_W};
    BtrcShimEvent event;
    memset(&event, 0, sizeof event);
    event.type = down ? BTRC_SHIM_EVENT_KEY_DOWN : BTRC_SHIM_EVENT_KEY_UP;
    event.window = window;
    event.scancode = scancodes[(ordinal - 1) % 4];
    event.down = down ? 1 : 0;
    event.data1 = ordinal;
    event.data2 = ORDINAL_MARK;
    push(&event, NULL);
}

void eventBoundaryText(unsigned int window, unsigned int control, const char *text) {
    BtrcShimEvent event;
    memset(&event, 0, sizeof event);
    event.type = BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED;
    event.window = window;
    event.control = control;
    push(&event, text);
}

int eventBoundaryQueued(void) {
    /* Count the injected classes without counting or removing permitted wakes. */
    return btrcGtkQueued(BTRC_SHIM_EVENT_KEY_DOWN, BTRC_SHIM_EVENT_KEY_UP) +
           btrcGtkQueued(BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED) +
           btrcGtkQueued(BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED, BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED);
}

void eventBoundaryClose(unsigned int window) {
    BtrcShimEvent event;
    memset(&event, 0, sizeof event);
    event.type = BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window = window;
    int before = admitted;
    push(&event, NULL);
    if (armed && admitted == before) { abort(); }
}

void eventBoundaryDisarm(void) { armed = false; btrcGtkQueueFilter(NULL); }
