/* Exercise the software client separately from the compositor input probe. */
#include "Client.h"
#include <assert.h>
#include <pthread.h>
#include <poll.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void waitFrame(BtrcWaylandDisplay *display, BtrcWaylandWindow *window, unsigned previous) {
    long long end = btrcWaylandMilliseconds() + 3000;
    while (btrcWaylandWindowFrames(window) == previous && btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(display, 100) >= 0);
    }
    assert(btrcWaylandWindowFrames(window) != previous && btrcWaylandWindowMapped(window));
}

static void *wake(void *display) {
    assert(btrcWaylandDisplayWake(display));
    return NULL;
}

static void lifecycle(BtrcWaylandDisplay *display, bool gpu, bool absent) {
    for (unsigned i = 0; i < 100; i++) {
        BtrcWaylandWindow *window = btrcWaylandWindowCreate(display, "btrc lifecycle", 64, 40);
        assert(window && btrcWaylandWindowMinimum(window, 32, 16));
        assert(btrcWaylandWindowShow(window));
        waitFrame(display, window, 0);
        BtrcWaylandGPUView *view = NULL;
        if (gpu || absent) {
            view = btrcWaylandWindowAttachGPU(window, 4, 2);
            if (gpu) {
                assert(view && btrcWaylandGPUViewSurface(view) && btrcWaylandGPUViewDisplay(view));
                assert(btrcWaylandGPUViewMove(view, 12, 8));
            } else { assert(!view); }
        }
        assert(btrcWaylandWindowResize(window, 96, 72));
        waitFrame(display, window, 1);
        assert(btrcWaylandWindowWidth(window) == 96 && btrcWaylandWindowHeight(window) == 72);
        assert(btrcWaylandWindowHide(window) && !btrcWaylandWindowMapped(window));
        assert(btrcWaylandWindowShow(window));
        waitFrame(display, window, 2);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(display, &event)) { }
        btrcWaylandGPUViewDestroy(view);
        btrcWaylandWindowDestroy(window);
    }
    pthread_t thread;
    assert(!pthread_create(&thread, NULL, wake, display));
    long long end = btrcWaylandMilliseconds() + 3000;
    bool woke = false;
    while (!woke && btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(display, 500) >= 0);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(display, &event)) { woke |= event.type == BTRC_SHIM_EVENT_USER; }
    }
    assert(woke && !pthread_join(thread, NULL));
    puts("100 map, resize, unmap, remap and destroy cycles; cross-thread wake passed");
}

static void paint(BtrcWaylandWindow *window) {
    int width = btrcWaylandWindowWidth(window) * btrcWaylandWindowScale(window);
    int height = btrcWaylandWindowHeight(window) * btrcWaylandWindowScale(window);
    uint32_t *pixels = calloc((size_t)width * height, sizeof(*pixels));
    assert(pixels);
    for (size_t i = 0; i < (size_t)width * height; i++) { pixels[i] = 0xff25b37du; }
    assert(btrcWaylandWindowPaint(window, pixels, width, height, (size_t)width * 4));
    free(pixels);
}

static void interactive(BtrcWaylandDisplay *display) {
    BtrcWaylandWindow *window = btrcWaylandWindowCreate(display, "btrc input and pixels", 160, 100);
    assert(window);
    btrcWaylandWindowTextInput(window, true);
    paint(window);
    assert(btrcWaylandWindowShow(window));
    waitFrame(display, window, 0);
    puts("ready");
    fflush(stdout);
    bool pressed = false, released = false, wheel = false, enter = false, shortcut = false, scaled = false;
    bool close = false;
    char text[32] = "";
    long long end = btrcWaylandMilliseconds() + 15000;
    while (!close && btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(display, 100) >= 0);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(display, &event)) {
            if (event.window != btrcWaylandWindowId(window)) { continue; }
            switch (event.type) {
            case BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN:
                pressed |= event.button == 1 && event.x >= 0 && event.x < 160 && event.y >= 0 && event.y < 100;
                break;
            case BTRC_SHIM_EVENT_MOUSE_BUTTON_UP: released |= event.button == 1; break;
            case BTRC_SHIM_EVENT_MOUSE_WHEEL: wheel |= event.wheelY == 1; break;
            case BTRC_SHIM_EVENT_KEY_DOWN:
                enter |= event.key == BTRC_SHIM_KEY_RETURN;
                shortcut |= event.key == BTRC_SHIM_KEY_A && (event.modifiers & BTRC_SHIM_MOD_CTRL);
                break;
            case BTRC_SHIM_EVENT_TEXT_INPUT:
                assert(strlen(text) + strlen(event.text) < sizeof(text));
                strcat(text, event.text);
                break;
            case BTRC_SHIM_EVENT_WINDOW_DISPLAY_SCALE_CHANGED:
                scaled |= btrcWaylandWindowScale(window) == 2;
                paint(window);
                break;
            case BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED: close = true; break;
            }
        }
    }
    printf("pressed %d released %d wheel %d enter %d ctrl-a %d scale2 %d close %d text %s\n",
           pressed, released, wheel, enter, shortcut, scaled, close, text);
    fflush(stdout);
    assert(pressed && released && wheel && enter && shortcut && scaled && close && !strcmp(text, "Aé🟢"));
    btrcWaylandWindowDestroy(window);
}

static void cursorShapes(BtrcWaylandDisplay *d, bool coreOnly) {
    /* Exercise the core-protocol fallback even on a modern compositor. */
    if (coreOnly) { d->cursorManager = 0; }
    BtrcWaylandWindow *w = btrcWaylandWindowCreate(d, "btrc input and pixels", 160, 100);
    assert(w);
    paint(w);
    assert(btrcWaylandWindowShow(w));
    waitFrame(d, w, 0);
    puts(d->cursorManager ? "system shapes" : "core shapes");
    fflush(stdout);
    bool closed = false;
    long long end = btrcWaylandMilliseconds() + 12000;
    while (!closed && btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(d, 100) >= 0);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(d, &event)) {
            if (event.type == BTRC_SHIM_EVENT_MOUSE_MOTION || event.type == BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER) {
                btrcWaylandWindowCursor(w, event.x < 80 ? BTRC_SHIM_CURSOR_DEFAULT : BTRC_SHIM_CURSOR_TEXT);
                assert(btrcWaylandRoundtrip(d->wire, 2000));
                printf("pointer %d\n", (int)event.x);
                fflush(stdout);
            }
            if (event.type == BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED) { closed = true; }
        }
    }
    assert(closed);
    btrcWaylandWindowDestroy(w);
}

static void popupWindow(BtrcWaylandDisplay *d) {
    BtrcWaylandWindow *w = btrcWaylandWindowCreate(d, "btrc input and pixels", 160, 100);
    assert(w && btrcWaylandWindowShow(w));
    waitFrame(d, w, 0);
    int scale = btrcWaylandWindowScale(w);
    size_t factor = (size_t)scale * scale;
    uint32_t *background = malloc(160 * 100 * factor * 4), *popup = malloc(72 * 26 * factor * 4);
    assert(background && popup);
    for (size_t i = 0; i < 160 * 100 * factor; i++) { background[i] = 0xff25b37d; }
    for (size_t i = 0; i < 72 * 26 * factor; i++) { popup[i] = 0xffab316d; }
    assert(btrcWaylandWindowPaint(w, background, 160*scale, 100*scale, (size_t)160*scale*4));
    free(background);
    puts("ready"); fflush(stdout);
    struct pollfd input = {.fd = STDIN_FILENO, .events = POLLIN};
    for (;;) {
        assert(btrcWaylandDisplayPoll(d, 10) >= 0);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(d, &event)) {
            if (event.type == BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN) { puts("parent click"); fflush(stdout); }
        }
        if (poll(&input, 1, 0) <= 0) { continue; }
        char command;
        if (read(input.fd, &command, 1) != 1 || command == 'q') { break; }
        if (command == 'p') { assert(btrcWaylandWindowPopup(w, 132, 65, 72, 26, popup)); }
        else if (command == 'g') { assert(btrcWaylandWindowAttachGPU(w, 10, 10)); }
        else if (command == 'h') { btrcWaylandWindowClosePopup(w); }
        else if (command == 'w') { assert(btrcWaylandWindowHide(w)); }
        else { assert(0); }
        puts("ok"); fflush(stdout);
    }
    btrcWaylandWindowDestroy(w);
    free(popup);
}

static void exportParent(BtrcWaylandDisplay *d, bool v1, bool gpu) {
    if (v1) { d->exporterName[1] = 0; }
    BtrcWaylandWindow *w = btrcWaylandWindowCreate(d, "btrc portal parent", 160, 100);
    assert(w && !btrcWaylandWindowExport(w) && btrcWaylandWindowShow(w));
    waitFrame(d, w, 0);
    if (!d->exporterName[v1 ? 0 : 1]) { puts("exporter unavailable"); exit(77); }
    for (unsigned i = 0; i < 2; ++i) {
        BtrcWaylandExport *token = btrcWaylandWindowExport(w);
        assert(token && btrcWaylandRoundtrip(d->wire, 3000));
        const char *identifier = btrcWaylandExportIdentifier(token);
        assert(identifier && !strncmp(identifier, "wayland:", 8) && identifier[8]);
        puts(identifier); fflush(stdout);
        assert(getchar() == '\n');
        if (i == 0) {
            if (gpu) { assert(btrcWaylandWindowAttachGPU(w, 0, 0)); }
            btrcWaylandExportRelease(token);
        } else {
            btrcWaylandWindowDestroy(w);
            assert(!btrcWaylandExportIdentifier(token));
            btrcWaylandExportRelease(token);
        }
        assert(btrcWaylandRoundtrip(d->wire, 3000));
    }
}

static void composition(BtrcWaylandDisplay *d, bool gpu) {
    BtrcWaylandWindow *w = btrcWaylandWindowCreate(d, "btrc input and pixels", 160, 100);
    assert(w && d->textManager);
    btrcWaylandWindowTextInput(w, true);
    assert(btrcWaylandWindowShow(w));
    waitFrame(d, w, 0);
    if (gpu) { assert(btrcWaylandWindowAttachGPU(w, 0, 0)); }
    puts("text window ready"); fflush(stdout);
    unsigned state = 0;
    long long end = btrcWaylandMilliseconds() + 12000;
    while (state < 5 && btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(d, 100) >= 0);
        BtrcShimEvent e;
        while (btrcWaylandDisplayPop(d, &e)) {
            if (e.type == BTRC_SHIM_EVENT_TEXT_EDITING) {
                if (state == 0) { assert(!strcmp(e.text, "ä日") && e.data1 == 1 && e.data2 == 1); puts("preedit"); fflush(stdout); }
                else if (state == 1 || state == 4) { assert(!e.text[0]); }
                else {
                    assert(state == 3 && !strcmp(e.text, "🟢") && e.data1 == 1 && e.data2 == 0);
                    btrcWaylandUpdateTextInputs(w, true);
                }
                ++state;
            } else if (e.type == BTRC_SHIM_EVENT_TEXT_INPUT) {
                assert(state == 2 && !strcmp(e.text, "完成"));
                ++state;
            }
        }
    }
    assert(state == 5);
    btrcWaylandWindowDestroy(w);
}

/* A focused editor gets ordinary key text immediately. Declining it in this
 * observer must still leave an unsubscribed window's public event queue empty
 * of text, as it would be for a software-only application with no editor. */
static unsigned letters;
static bool observeSceneText(BtrcWaylandDisplay *display, const BtrcShimEvent *event, bool *handled) {
    (void)display;
    *handled = false;
    if (event->type == BTRC_SHIM_EVENT_TEXT_INPUT) {
        assert(letters < 5 && event->text && event->text[0] == "draft"[letters] && !event->text[1]);
        ++letters;
    }
    return true;
}

static void sceneText(BtrcWaylandDisplay *display) {
    BtrcWaylandWindow *window = btrcWaylandWindowCreate(display, "btrc input and pixels", 120, 80);
    assert(window && btrcWaylandWindowShow(window));
    waitFrame(display, window, 0);
    display->routeInput = observeSceneText;
    puts("keyboard ready");
    fflush(stdout);
    long long end = btrcWaylandMilliseconds() + 5000;
    while (letters < 5 && btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(display, 50) >= 0);
        BtrcShimEvent event;
        while (btrcWaylandDisplayPop(display, &event)) { assert(event.type != BTRC_SHIM_EVENT_TEXT_INPUT); }
    }
    assert(letters == 5);
    btrcWaylandWindowDestroy(window);
}

static void keyRepeat(BtrcWaylandDisplay *display) {
    BtrcWaylandWindow *window = btrcWaylandWindowCreate(display, "btrc input and pixels", 120, 80);
    assert(window && btrcWaylandWindowShow(window));
    waitFrame(display, window, 0);
    puts("keyboard ready");
    fflush(stdout);
    unsigned presses = 0, repeats = 0;
    bool released = false;
    long long end = btrcWaylandMilliseconds() + 6000;
    while (btrcWaylandMilliseconds() < end) {
        assert(btrcWaylandDisplayPoll(display, 50) >= 0);
        BtrcShimEvent e;
        while (btrcWaylandDisplayPop(display, &e)) {
            if (e.key != BTRC_SHIM_KEY_RETURN) { continue; }
            if (e.type == BTRC_SHIM_EVENT_KEY_DOWN) {
                assert(!released);
                if (e.repeat) { ++repeats; } else { ++presses; }
            } else if (e.type == BTRC_SHIM_EVENT_KEY_UP) {
                assert(!e.repeat);
                released = true;
                end = btrcWaylandMilliseconds() + 250;
            }
        }
    }
    printf("initial %u repeated %u released %d\n", presses, repeats, released);
    assert(presses == 1 && repeats >= 2 && released);
    btrcWaylandWindowDestroy(window);
}

int main(int argc, char **argv) {
    assert(!getenv("DISPLAY"));
    BtrcWaylandDisplay *display = btrcWaylandDisplayOpen();
    assert(display);
    if (argc == 2 && !strcmp(argv[1], "interactive")) { interactive(display); }
    else if (argc == 2 && (!strcmp(argv[1], "cursor") || !strcmp(argv[1], "core-cursor"))) { cursorShapes(display, !strcmp(argv[1], "core-cursor")); }
    else if (argc == 2 && !strcmp(argv[1], "popup")) { popupWindow(display); }
    else if (argc == 2 && !strncmp(argv[1], "export-", 7)) { exportParent(display, strstr(argv[1], "v1") != NULL, strstr(argv[1], "gpu") != NULL); }
    else if (argc == 2 && (!strcmp(argv[1], "ime") || !strcmp(argv[1], "gpu-ime"))) { composition(display, !strcmp(argv[1], "gpu-ime")); }
    else if (argc == 2 && !strcmp(argv[1], "scene-text")) { sceneText(display); }
    else if (argc == 2 && !strcmp(argv[1], "repeat")) { keyRepeat(display); }
    else if (argc == 2 && !strcmp(argv[1], "disconnect")) {
        BtrcWaylandWindow *window = btrcWaylandWindowCreate(display, "btrc disconnect", 48, 48);
        assert(window && btrcWaylandWindowShow(window));
        waitFrame(display, window, 0);
        puts("ready");
        fflush(stdout);
        long long end = btrcWaylandMilliseconds() + 3000;
        int result;
        do { result = btrcWaylandDisplayPoll(display, 100); } while (result >= 0 && btrcWaylandMilliseconds() < end);
        assert(result < 0 && btrcWaylandDisplayError(display)[0]);
        btrcWaylandWindowDestroy(window);
    } else { lifecycle(display, argc == 2 && !strcmp(argv[1], "gpu"), argc == 2 && !strcmp(argv[1], "without-gpu")); }
    btrcWaylandDisplayClose(display);
    return 0;
}
