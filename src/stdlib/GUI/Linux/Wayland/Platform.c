/* The desktop GUI shim owns one event loop per process. Only its wake
 * operation crosses threads, as permitted by the wire transport. */
#define _POSIX_C_SOURCE 200809L
#include "Platform.h"
#include "Client.h"
#include "Clipboard.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static _Atomic(BtrcWaylandDisplay *) display;
static BtrcShimWindow *windows;
static pthread_t thread;
static int openError;
static bool disconnected;

bool btrcShimInit(void) {
    if (display) { return !disconnected; }
    BtrcWaylandDisplay *opened = btrcWaylandDisplayOpen();
    if (!opened) { openError = errno; return false; }
    thread = pthread_self();
    opened->routeInput = btrcWaylandSceneInput;
    display = opened;
    return true;
}

bool btrcShimIsMainThread(void) { return !display || pthread_equal(thread, pthread_self()); }

const char *btrcShimError(void) {
    return display ? btrcWaylandDisplayError(display) : (openError ? strerror(openError) : "");
}

unsigned long long btrcShimTicksNS(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (unsigned long long)now.tv_sec * 1000000000 + (unsigned long long)now.tv_nsec;
}

BtrcShimWindow *btrcWaylandPlatformWindows(void) { return windows; }

BtrcShimWindow *btrcShimWindowCreate(const char *title, int width, int height) {
    if (!display || disconnected) { return NULL; }
    BtrcShimWindow *w = calloc(1, sizeof(*w));
    if (!w) { return NULL; }
    w->native = btrcWaylandWindowCreate(display, title, width, height);
    if (!w->native) { free(w); return NULL; }
    w->next = windows;
    windows = w;
    return w;
}

void btrcShimWindowDestroy(BtrcShimWindow *w) {
    if (!w) { return; }
    BtrcShimWindow **where = &windows;
    while (*where && *where != w) { where = &(*where)->next; }
    if (*where) { *where = w->next; }
    btrcWaylandSceneClose(w);
    btrcWaylandWindowDestroy(w->native);
    free(w);
}

unsigned int btrcShimWindowId(BtrcShimWindow *w) { return btrcWaylandWindowId(w->native); }
bool btrcShimWindowShow(BtrcShimWindow *w) { return btrcWaylandWindowShow(w->native); }
bool btrcShimWindowHide(BtrcShimWindow *w) { return btrcWaylandWindowHide(w->native); }
bool btrcShimWindowIsHidden(BtrcShimWindow *w) { return !w->native->visible; }
bool btrcShimWindowIsMinimized(BtrcShimWindow *w) { return w->native->suspended; }
void btrcShimWindowSetCursor(BtrcShimWindow *w, int kind) { btrcWaylandWindowCursor(w->native, kind); }
void btrcShimWindowSetTitle(BtrcShimWindow *w, const char *title) { btrcWaylandWindowTitle(w->native, title); }
void btrcShimWindowSetSize(BtrcShimWindow *w, int width, int height) { btrcWaylandWindowResize(w->native, width, height); }
void btrcShimWindowSetMinimumSize(BtrcShimWindow *w, int width, int height) { btrcWaylandWindowMinimum(w->native, width, height); }
int btrcShimWindowWidth(BtrcShimWindow *w) { return btrcWaylandWindowWidth(w->native); }
int btrcShimWindowHeight(BtrcShimWindow *w) { return btrcWaylandWindowHeight(w->native); }
int btrcShimWindowPixelWidth(BtrcShimWindow *w) { return btrcShimWindowWidth(w) * btrcWaylandWindowScale(w->native); }
int btrcShimWindowPixelHeight(BtrcShimWindow *w) { return btrcShimWindowHeight(w) * btrcWaylandWindowScale(w->native); }
double btrcShimWindowPixelDensity(BtrcShimWindow *w) { return btrcWaylandWindowScale(w->native); }
bool btrcShimWindowSupportsSoftware(BtrcShimWindow *w) { return w != NULL; }
bool btrcShimWindowShowsPictures(BtrcShimWindow *w) { return w->gpu == NULL; }

void btrcShimWindowStartTextInput(BtrcShimWindow *w) { btrcWaylandWindowTextInput(w->native, true); }
void btrcShimWindowStopTextInput(BtrcShimWindow *w) { btrcWaylandWindowTextInput(w->native, false); }
void btrcShimWindowClearComposition(BtrcShimWindow *w) {
    btrcWaylandUpdateTextInputs(w->native, true);
}
void btrcShimWindowSetTextInputArea(BtrcShimWindow *w, int x, int y, int width, int height) {
    BtrcWaylandWindow *n = w->native;
    if (n->textX == x && n->textY == y && n->textWidth == width && n->textHeight == height) { return; }
    n->textX = x; n->textY = y; n->textWidth = width; n->textHeight = height;
    if (n->textInput) { btrcWaylandUpdateTextInputs(n, false); }
}
bool btrcShimWindowTextInputActive(BtrcShimWindow *w) { return w->native->textInput; }

bool btrcShimPushWake(void) {
    BtrcWaylandDisplay *current = display;
    return current && btrcWaylandDisplayWake(current);
}

int btrcShimWaitEvent(BtrcShimEvent *out, int timeout) {
    if (!display || !out) { return 0; }
    long long deadline = btrcWaylandMilliseconds() + timeout;
    int remaining = timeout;
    for (;;) {
        if (btrcWaylandDisplayPop(display, out)) { return 1; }
        if (disconnected) { return 0; }
        int result = btrcWaylandDisplayPoll(display, btrcWaylandSceneAdvance(remaining));
        if (result < 0) {
            disconnected = true;
            *out = (BtrcShimEvent){.type = BTRC_SHIM_EVENT_QUIT};
            return 1;
        }
        if (btrcWaylandDisplayPop(display, out)) { return 1; }
        if (timeout >= 0) {
            long long left = deadline - btrcWaylandMilliseconds();
            if (left <= 0) { return 0; }
            remaining = (int)left;
        }
    }
}

int btrcShimPollEvent(BtrcShimEvent *out) { return btrcShimWaitEvent(out, 0); }

int btrcShimAutomationDisplay(void) { return display ? BTRC_SHIM_DISPLAY_WAYLAND : BTRC_SHIM_DISPLAY_NONE; }

unsigned int btrcShimWindowNamed(const char *title) {
    for (BtrcShimWindow *w = windows; w; w = w->next) {
        if (title && !strcmp(w->native->title, title)) { return btrcShimWindowId(w); }
    }
    return 0;
}

int btrcShimAutomationWindows(void) {
    int n = 0;
    for (BtrcShimWindow *w = windows; w; w = w->next) { ++n; }
    return n;
}

unsigned int btrcShimModState(void) { return display ? display->modifiers : 0; }

unsigned long btrcShimAutomationSerial(void) { return display ? display->arrivals : 0; }

int btrcShimAutomationPointer(unsigned int window, double *x, double *y) {
    return display && x && y && btrcWaylandPointerPosition(display, window, x, y);
}

int btrcShimAutomationAwait(unsigned long serial, int timeout) {
    if (!display || disconnected) { return 0; }
    if (timeout <= 0) { return serial != display->arrivals; }
    long long deadline = btrcWaylandMilliseconds() + timeout;
    unsigned long seen = serial;
    long long quiet = 0;
    for (;;) {
        long long now = btrcWaylandMilliseconds();
        if (seen != display->arrivals) { seen = display->arrivals; quiet = now + 20; }
        if (now >= deadline || (quiet && now >= quiet)) { return seen != serial; }
        int wait = (int)((quiet && quiet < deadline ? quiet : deadline) - now);
        if (btrcWaylandDisplayPoll(display, wait) < 0) { return 0; }
    }
}

bool btrcShimSetClipboardText(const char *text) { return btrcWaylandClipboardSet(btrcWaylandActiveClipboard(display), text); }
bool btrcShimHasClipboardText(void) { return btrcWaylandClipboardHas(btrcWaylandActiveClipboard(display)); }
char *btrcShimGetClipboardText(void) { return btrcWaylandClipboardRead(btrcWaylandActiveClipboard(display)); }
void btrcShimFree(char *text) { free(text); }
