/* The conformance probe on iOS and iPadOS: real input, sent to the simulated
 * device's screen from beside it. The simulator's own HID service takes it
 * (tools/target_hosts/ios/simhid.m, which the driver starts on the host and
 * names with BTRC_CONFORMANCE_HID, a port of the host both share), so a
 * touch, a key and a wheel arrive as a person's finger, keyboard and mouse
 * would, through the system, to whatever is on the screen.
 *
 * The provider's shim says where a window's content is on the screen and
 * whether what was sent has arrived (GUI/IOS/UIKitShim.m, "automation").
 * Neither delivers input. The probe's positions are in points, as the
 * screen's are. */
#include "../ConformanceProbe.h"
#include "../shim/RealInput.h"
#include "../shim/ShimProbe.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

unsigned int btrcShimWindowNamed(const char *title);
unsigned long btrcShimAutomationSerial(void);
int btrcShimAutomationAwait(unsigned long serial, int timeoutMilliseconds);
int btrcUIKitAutomationOrigin(unsigned int window, double *x, double *y);
int btrcUIKitAutomationScene(double *x, double *y, double *width, double *height);
int btrcShimAutomationWindows(void);
void btrcUIKitAutomationScreen(double *width, double *height);

enum { ARRIVAL_MILLISECONDS = 500, SEARCH_MILLISECONDS = 60, APPEARANCE_ATTEMPTS = 160, NOTCH_POINTS = 48, FRAME_MICROSECONDS = 16667 };
/* The keyboard page's usages, and simhid's modifier for Command. */
enum { USAGE_A = 0x04, USAGE_W = 0x1A, USAGE_RETURN = 0x28, USAGE_ESCAPE = 0x29, USAGE_BACKSPACE = 0x2A, USAGE_TAB = 0x2B, USAGE_RIGHT = 0x4F, USAGE_LEFT = 0x50, USAGE_DOWN = 0x51, USAGE_UP = 0x52, COMMAND = 8 };

static struct { pthread_mutex_t lock; int socket; bool tried; bool down; bool hovered; double x, y; } host = { .lock = PTHREAD_MUTEX_INITIALIZER, .socket = -1 };

static void trace(const char *what, const char *detail) {
    const char *wanted = getenv("BTRC_CONFORMANCE_TRACE");
    if (wanted && strcmp(wanted, "1") == 0) { fprintf(stderr, "probe: %s %s\n", what, detail); }
}

/* The one connection to the host's injector, made when first needed. */
static bool connected(void) {
    if (host.tried) { return host.socket >= 0; }
    host.tried = true;
    const char *allowed = getenv("BTRC_UI_PRIVATE_SESSION");
    const char *port = getenv("BTRC_CONFORMANCE_HID");
    if (!allowed || strcmp(allowed, "1") != 0 || !port || atoi(port) <= 0 || atoi(port) > 65535) { return false; }
    struct sockaddr_in address;
    memset(&address, 0, sizeof address);
    address.sin_family = AF_INET;
    address.sin_port = htons((unsigned short)atoi(port));
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int made = socket(AF_INET, SOCK_STREAM, 0);
    if (made < 0) { return false; }
    int on = 1;
    setsockopt(made, IPPROTO_TCP, TCP_NODELAY, &on, sizeof on);
    if (connect(made, (struct sockaddr *)&address, sizeof address) != 0) { close(made); return false; }
    host.socket = made;
    return true;
}

/* One request and its one-line answer; true when the injector sent the input. */
static bool ask(const char *format, ...) {
    char line[512];
    char answer[256];
    va_list arguments;
    va_start(arguments, format);
    int length = vsnprintf(line, sizeof line - 1u, format, arguments);
    va_end(arguments);
    if (length <= 0 || (size_t)length >= sizeof line - 1u) { return false; }
    line[length++] = '\n';
    bool sent = false;
    pthread_mutex_lock(&host.lock);
    if (connected() && write(host.socket, line, (size_t)length) == (ssize_t)length) {
        size_t have = 0;
        while (have < sizeof answer - 1u) {
            ssize_t got = read(host.socket, answer + have, 1u);
            if (got <= 0 || answer[have] == '\n') { break; }
            have++;
        }
        answer[have] = '\0';
        sent = strncmp(answer, "OK", 2u) == 0;
        if (!sent) { trace(line, answer); }
    }
    pthread_mutex_unlock(&host.lock);
    return sent;
}

static void arrived(unsigned long serial, int milliseconds) { btrcShimAutomationAwait(serial, milliseconds); }

/* Where a content position is on the screen. A window that was only just
 * shown is not on the screen yet: the scene and the system still have to
 * agree on it. */
static bool locate(const char *title, double x, double y, double *screenX, double *screenY) {
    unsigned int window = btrcShimWindowNamed(title);
    if (!window) { return false; }
    for (int attempt = 0; attempt < APPEARANCE_ATTEMPTS; attempt++) {
        double left = 0.0;
        double top = 0.0;
        if (btrcUIKitAutomationOrigin(window, &left, &top)) {
            *screenX = left + x;
            *screenY = top + y;
            return true;
        }
        arrived(btrcShimAutomationSerial(), SEARCH_MILLISECONDS);
    }
    trace("not on show", title);
    return false;
}

/* A finger on the screen moves; with none down, the pointer of a mouse does,
 * where the device has one (a phone does not, and the move is the hand's own).
 * The system drops what follows a pointer's move within the same frame of
 * the display, so the move is let arrive, and a frame pass, before more. */
static bool move(double x, double y) {
    bool same = host.x == x && host.y == y;
    host.x = x;
    host.y = y;
    if (host.down) { return ask("MOVE %.2f %.2f", x, y); }
    if (same && host.hovered) { return true; }
    unsigned long serial = btrcShimAutomationSerial();
    host.hovered = ask("HOVER %.2f %.2f", x, y);
    if (host.hovered) {
        arrived(serial, ARRIVAL_MILLISECONDS);
        usleep(FRAME_MICROSECONDS * 4);
    }
    return true;
}

static bool button(bool down) {
    if (!ask("%s %.2f %.2f", down ? "DOWN" : "UP", host.x, host.y)) { return false; }
    host.down = down;
    return true;
}

/* A notch moves a document by this many points, as the provider's own scrolling has it. */
static bool wheel(double deltaX, double deltaY) { return ask("SCROLL %.2f %.2f %.2f %.2f", host.x, host.y, deltaX * NOTCH_POINTS, deltaY * NOTCH_POINTS); }

static bool key(int key) {
    switch (key) {
    case CONFORMANCE_KEY_RETURN: return ask("KEY %d 0", USAGE_RETURN);
    case CONFORMANCE_KEY_ESCAPE: return ask("KEY %d 0", USAGE_ESCAPE);
    case CONFORMANCE_KEY_TAB: return ask("KEY %d 0", USAGE_TAB);
    case CONFORMANCE_KEY_LEFT: return ask("KEY %d 0", USAGE_LEFT);
    case CONFORMANCE_KEY_RIGHT: return ask("KEY %d 0", USAGE_RIGHT);
    case CONFORMANCE_KEY_UP: return ask("KEY %d 0", USAGE_UP);
    case CONFORMANCE_KEY_DOWN: return ask("KEY %d 0", USAGE_DOWN);
    case CONFORMANCE_KEY_BACKSPACE: return ask("KEY %d 0", USAGE_BACKSPACE);
    case CONFORMANCE_KEY_SELECT_ALL: return ask("KEY %d %d", USAGE_A, COMMAND);
    default: return false;
    }
}

/* One character at a time, each as the keys the keyboard has for it. */
static bool text(const char *text, void (*typed)(void)) {
    for (const unsigned char *at = (const unsigned char *)text; *at; ) {
        char encoded[16] = {0};
        int length = (*at & 0x80) == 0 ? 1 : (*at & 0xE0) == 0xC0 ? 2 : (*at & 0xF0) == 0xE0 ? 3 : 4;
        size_t used = 0;
        for (int index = 0; index < length && at[index]; index++) { used += (size_t)snprintf(encoded + used, sizeof encoded - used, "%%%02X", at[index]); }
        at += used / 3u;
        if (!ask("TEXT %s", encoded)) { return false; }
        typed();
    }
    return true;
}

/* The window on show has the screen and the keyboard: there is nothing to raise. */
static bool activate(const char *title) {
    double x = 0.0;
    double y = 0.0;
    return locate(title, 0.0, 0.0, &x, &y);
}

/* The keyboard's close request is Command-W. */
static bool closeWindow(const char *title) { return activate(title) && ask("KEY %d %d", USAGE_W, COMMAND); }

static bool origin(const char *title, double *x, double *y) { return locate(title, 0.0, 0.0, x, y); }

static void extent(double *width, double *height) { btrcUIKitAutomationScreen(width, height); }

/* Every window has the whole scene, at first and always. */
static bool fillsScreen(void) { return true; }

static const RealInput simulator = {
    .move = move, .button = button, .wheel = wheel, .key = key, .text = text, .activate = activate, .close = closeWindow,
    .origin = origin, .extent = extent, .fillsScreen = fillsScreen, .keepsScreen = fillsScreen,
};

const RealInput *shimProbeInput(void) {
    pthread_mutex_lock(&host.lock);
    bool ready = connected();
    pthread_mutex_unlock(&host.lock);
    return ready ? &simulator : NULL;
}

static void typed(void) { arrived(btrcShimAutomationSerial(), SEARCH_MILLISECONDS); }

/* Send one input at a content position and wait for it to arrive. */
static int pointed(const char *title, double x, double y, bool (*send)(void *), void *with) {
    double screenX = 0.0;
    double screenY = 0.0;
    if (!shimProbeInput() || !locate(title, x, y, &screenX, &screenY)) { return 0; }
    bool dragging = host.down;
    unsigned long serial = btrcShimAutomationSerial();
    if (!move(screenX, screenY)) { return 0; }
    /* A pointer's move has arrived by now; a finger's drag arrives with what follows it. */
    if (!dragging) { serial = btrcShimAutomationSerial(); }
    if (send && !send(with)) { return 0; }
    if (send || dragging) { arrived(serial, ARRIVAL_MILLISECONDS); }
    return 1;
}

static bool press(void *unused) { (void)unused; return button(true); }

static bool release(void *unused) { (void)unused; return button(false); }

static bool turn(void *deltas) { return wheel(((const double *)deltas)[0], ((const double *)deltas)[1]); }

int conformanceProbeMove(const char *title, double x, double y) { return pointed(title, x, y, NULL, NULL); }

int conformanceProbePress(const char *title, double x, double y) { return pointed(title, x, y, press, NULL); }

int conformanceProbeRelease(const char *title, double x, double y) { return pointed(title, x, y, release, NULL); }

int conformanceProbeWheel(const char *title, double x, double y, double deltaX, double deltaY) {
    double deltas[2] = { deltaX, deltaY };
    return pointed(title, x, y, turn, deltas);
}

int conformanceProbeKey(const char *title, int pressed) {
    if (!shimProbeInput() || pressed < CONFORMANCE_KEY_RETURN || pressed > CONFORMANCE_KEY_SELECT_ALL || !activate(title)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!key(pressed)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int conformanceProbeText(const char *title, const char *typedText) {
    if (!shimProbeInput() || !activate(title)) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!text(typedText, typed)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

int conformanceProbeClose(const char *title) {
    if (!shimProbeInput()) { return 0; }
    unsigned long serial = btrcShimAutomationSerial();
    if (!closeWindow(title)) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS);
    return 1;
}

/* BTRC_CONFORMANCE_SCENE says what scene the cases are to run in on a tablet,
 * whose system keeps a scene's size from one launch of an app to the next:
 * "whole" is the whole screen, and "compact" a scene as narrow as a phone's,
 * which is what a split view or a small window gives an app. The first case
 * to show a window makes it so, as a person would: by dragging the corner of
 * the scene's window. A scene that will not be made so ends the program: no
 * case may pass in a scene it was not asked for. */
enum { SCENE_REGULAR = 1, SCENE_COMPACT = 2, SCENE_DRAGS = 8, SCENE_HANDLE_INSET = 8, SCENE_ARRIVAL_ATTEMPTS = 100, SCENE_STEPS = 8 };

/* Drag the scene's corner by this much, and say what the scene is then. */
static int dragCorner(double byX, double byY, double *x, double *y, double *width, double *height) {
    double cornerX = *x + *width - SCENE_HANDLE_INSET;
    double cornerY = *y + *height - SCENE_HANDLE_INSET;
    unsigned long serial = btrcShimAutomationSerial();
    bool dragged = ask("DOWN %.2f %.2f", cornerX, cornerY);
    for (int step = 1; step <= SCENE_STEPS && dragged; step++) {
        dragged = ask("MOVE %.2f %.2f", cornerX + byX * step / SCENE_STEPS, cornerY + byY * step / SCENE_STEPS);
        usleep(FRAME_MICROSECONDS * 2);
    }
    dragged = ask("UP %.2f %.2f", cornerX + byX, cornerY + byY) && dragged;
    if (!dragged) { return 0; }
    arrived(serial, ARRIVAL_MILLISECONDS * 2);
    usleep(FRAME_MICROSECONDS * 30);
    return btrcUIKitAutomationScene(x, y, width, height);
}

static void arrangeScene(void) {
    static bool settled;
    const char *wanted = getenv("BTRC_CONFORMANCE_SCENE");
    double x = 0.0, y = 0.0, width = 0.0, height = 0.0, screenWidth = 0.0, screenHeight = 0.0;
    if (settled || !wanted || !shimProbeInput() || btrcShimAutomationWindows() == 0) { return; }
    bool compact = strcmp(wanted, "compact") == 0;
    if (!compact && strcmp(wanted, "whole") != 0) { return; }
    int kind = 0;
    for (int attempt = 0; attempt < SCENE_ARRIVAL_ATTEMPTS && kind == 0; attempt++) {
        kind = btrcUIKitAutomationScene(&x, &y, &width, &height);
        if (kind == 0) { arrived(btrcShimAutomationSerial(), SEARCH_MILLISECONDS); }
    }
    /* No window was put on show: there is no scene to speak of yet. */
    if (kind == 0) { return; }
    btrcUIKitAutomationScreen(&screenWidth, &screenHeight);
    for (int drag = 0; drag < SCENE_DRAGS && kind != 0; drag++) {
        bool whole = width >= screenWidth && height >= screenHeight;
        if (compact ? kind == SCENE_COMPACT : whole) { break; }
        /* Inward a step at a time; outward to the screen's own corner and past it. */
        kind = compact ? dragCorner(-80.0, -96.0, &x, &y, &width, &height) : dragCorner(screenWidth - (x + width) + 40.0, screenHeight - (y + height) + 40.0, &x, &y, &width, &height);
    }
    bool made = compact ? kind == SCENE_COMPACT : (kind != 0 && width >= screenWidth && height >= screenHeight);
    fprintf(stderr, "probe: the scene %s %s (%.0f by %.0f)\n", made ? "is" : "would not become", compact ? "compact" : "the whole screen", width, height);
    fflush(stderr);
    if (!made) { exit(70); }
    settled = true;
}

/* The provider's turn drains what the main thread queued. */
void conformanceProbeService(void) { arrangeScene(); }

int conformanceProbeWindowSizing(void) { return CONFORMANCE_WINDOW_SIZING_SCREEN_ALWAYS; }
