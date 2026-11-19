/* Real input on X11: the XTEST extension, on the probe's own connection.
 * A bare X server has no window manager, so the probe also does that part:
 * it raises a window and gives it the keyboard, and asks it to close the way
 * a window manager does (WM_DELETE_WINDOW).
 *
 * Gamescope's session (a Steam Deck's Game Mode) is a compositor over
 * several X servers that gives the screen and its input to one application:
 * the first on the list Steam keeps on the first server's root, matched to
 * windows by the app id each carries. There the probe does Steam's part
 * too: it gives the window an app id of its own and puts that id at the
 * head of the list, and takes it off again when the process ends. */
#include "../shim/RealInput.h"
#include "../ConformanceProbe.h"
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XTest.h>
#include <X11/keysym.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The app id the probe's windows carry in a Gamescope session: "BTRC". */
enum { GAMESCOPE_APP = 0x42545243, GAMESCOPE_APPS = 16 };

static struct {
    Display *display;
    Window root;
    /* A key the layout leaves unused, lent to each character in turn. */
    KeyCode spare;
    /* Gamescope's first X server, where Steam's list is; NULL anywhere else. */
    Display *gamescope;
} x;

static bool titled(Window window, const char *title) {
    Atom utf8 = XInternAtom(x.display, "UTF8_STRING", False);
    Atom type = None;
    int format = 0;
    unsigned long count = 0;
    unsigned long remaining = 0;
    unsigned char *value = NULL;
    bool same = false;
    if (XGetWindowProperty(x.display, window, XInternAtom(x.display, "_NET_WM_NAME", False), 0, 1024, False, utf8, &type, &format, &count, &remaining, &value) == Success && value) {
        same = type == utf8 && strcmp((const char *)value, title) == 0;
        XFree(value);
        if (same) { return true; }
    }
    char *name = NULL;
    if (XFetchName(x.display, window, &name) && name) {
        same = strcmp(name, title) == 0;
        XFree(name);
    }
    return same;
}

/* The mapped top-level window with this title: a child of the root, or with
 * a reparenting window manager the client window inside one. */
static Window named(Window parent, const char *title, int depth) {
    Window root = None;
    Window above = None;
    Window *children = NULL;
    unsigned int count = 0;
    Window found = None;
    if (!XQueryTree(x.display, parent, &root, &above, &children, &count)) { return None; }
    for (unsigned int index = count; index > 0 && found == None; index--) {
        XWindowAttributes attributes;
        Window child = children[index - 1];
        if (!XGetWindowAttributes(x.display, child, &attributes) || attributes.map_state != IsViewable) { continue; }
        if (titled(child, title)) { found = child; }
        else if (depth > 0) { found = named(child, title, depth - 1); }
    }
    if (children) { XFree(children); }
    return found;
}

static bool flush(void) { XSync(x.display, False); return true; }

static bool x11Move(double px, double py) {
    XTestFakeMotionEvent(x.display, DefaultScreen(x.display), (int)px, (int)py, CurrentTime);
    return flush();
}

static bool x11Button(bool down) {
    XTestFakeButtonEvent(x.display, 1, down ? True : False, CurrentTime);
    return flush();
}

static void turn(unsigned int button, int notches) {
    for (int index = 0; index < notches; index++) {
        XTestFakeButtonEvent(x.display, button, True, CurrentTime);
        XTestFakeButtonEvent(x.display, button, False, CurrentTime);
    }
}

/* X has no wheel, only buttons: 4 and 5 scroll up and down, 6 and 7 left and right. */
static bool x11Wheel(double deltaX, double deltaY) {
    if (deltaY > 0) { turn(4, (int)deltaY); } else { turn(5, (int)-deltaY); }
    if (deltaX > 0) { turn(7, (int)deltaX); } else { turn(6, (int)-deltaX); }
    return flush();
}

static bool tap(KeySym keysym, bool control) {
    KeyCode code = XKeysymToKeycode(x.display, keysym);
    if (!code) { return false; }
    KeyCode modifier = control ? XKeysymToKeycode(x.display, XK_Control_L) : 0;
    if (modifier) { XTestFakeKeyEvent(x.display, modifier, True, CurrentTime); }
    XTestFakeKeyEvent(x.display, code, True, CurrentTime);
    XTestFakeKeyEvent(x.display, code, False, CurrentTime);
    if (modifier) { XTestFakeKeyEvent(x.display, modifier, False, CurrentTime); }
    return flush();
}

static bool x11Key(int key) {
    switch (key) {
    case CONFORMANCE_KEY_RETURN: return tap(XK_Return, false);
    case CONFORMANCE_KEY_ESCAPE: return tap(XK_Escape, false);
    case CONFORMANCE_KEY_TAB: return tap(XK_Tab, false);
    case CONFORMANCE_KEY_LEFT: return tap(XK_Left, false);
    case CONFORMANCE_KEY_RIGHT: return tap(XK_Right, false);
    case CONFORMANCE_KEY_UP: return tap(XK_Up, false);
    case CONFORMANCE_KEY_DOWN: return tap(XK_Down, false);
    case CONFORMANCE_KEY_BACKSPACE: return tap(XK_BackSpace, false);
    case CONFORMANCE_KEY_SELECT_ALL: return tap(XK_a, true);
    default: return false;
    }
}

static uint32_t nextScalar(const unsigned char **cursor) {
    const unsigned char *text = *cursor;
    uint32_t first = text[0];
    int more = first < 0x80 ? 0 : (first >> 5) == 0x6 ? 1 : (first >> 4) == 0xe ? 2 : (first >> 3) == 0x1e ? 3 : -1;
    if (first == 0 || more < 0) { return 0; }
    uint32_t value = more == 0 ? first : first & (0x3fu >> more);
    for (int index = 1; index <= more; index++) {
        if ((text[index] & 0xc0) != 0x80) { return 0; }
        value = (value << 6) | (text[index] & 0x3fu);
    }
    *cursor = text + more + 1;
    return value;
}

/* Each character is typed on the spare key, whose one symbol is changed to
 * it first: no layout has every character, and none needs a modifier then.
 * The window must have read the new layout before the key arrives, or it
 * reads the key with the layout of a later character. */
static bool x11Text(const char *text, void (*typed)(void)) {
    const unsigned char *cursor = (const unsigned char *)text;
    if (!x.spare) { return false; }
    while (*cursor) {
        uint32_t scalar = nextScalar(&cursor);
        if (!scalar) { return false; }
        KeySym symbol = scalar < 0x100 ? scalar : (0x01000000u | scalar);
        XChangeKeyboardMapping(x.display, x.spare, 1, &symbol, 1);
        XSync(x.display, False);
        typed();
        XTestFakeKeyEvent(x.display, x.spare, True, CurrentTime);
        XTestFakeKeyEvent(x.display, x.spare, False, CurrentTime);
        XSync(x.display, False);
        typed();
    }
    /* The key goes back unused: the server may outlive this process, and a
     * key left with a symbol is one fewer to lend next time. */
    KeySym none = NoSymbol;
    XChangeKeyboardMapping(x.display, x.spare, 1, &none, 1);
    XSync(x.display, False);
    typed();
    return true;
}

/* Write Steam's list without the probe's id, or with it at the head. */
static void gamescopeList(bool listed) {
    Window root = DefaultRootWindow(x.gamescope);
    Atom list = XInternAtom(x.gamescope, "GAMESCOPECTRL_BASELAYER_APPID", False);
    Atom type = None;
    int format = 0;
    unsigned long count = 0;
    unsigned long remaining = 0;
    unsigned char *value = NULL;
    unsigned long apps[GAMESCOPE_APPS + 1];
    int length = 0;
    if (listed) { apps[length++] = GAMESCOPE_APP; }
    if (XGetWindowProperty(x.gamescope, root, list, 0, GAMESCOPE_APPS, False, XA_CARDINAL, &type, &format, &count, &remaining, &value) == Success && value) {
        const unsigned long *present = (const unsigned long *)value;
        if (listed && count > 0 && present[0] == GAMESCOPE_APP) { XFree(value); return; }
        for (unsigned long index = 0; format == 32 && index < count && length <= GAMESCOPE_APPS; index++) {
            if (present[index] != GAMESCOPE_APP) { apps[length++] = present[index]; }
        }
        XFree(value);
    }
    XChangeProperty(x.gamescope, root, list, XA_CARDINAL, 32, PropModeReplace, (const unsigned char *)apps, length);
    XSync(x.gamescope, False);
}

static void gamescopeLeave(void) { if (x.gamescope) { gamescopeList(false); } }

/* A program that is stopped leaves the list as one that ends does: Gamescope
 * would go on giving the screen to a program that is gone. */
static void gamescopeStopped(int number) {
    gamescopeLeave();
    signal(number, SIG_DFL);
    raise(number);
}

/* This server's number among Gamescope's, or -1 when the session is not Gamescope's. */
static int gamescopeServer(void) {
    Atom type = None;
    int format = 0;
    unsigned long count = 0;
    unsigned long remaining = 0;
    unsigned char *value = NULL;
    int server = -1;
    if (XGetWindowProperty(x.display, x.root, XInternAtom(x.display, "GAMESCOPE_XWAYLAND_SERVER_ID", False), 0, 1, False, XA_CARDINAL, &type, &format, &count, &remaining, &value) == Success && value) {
        if (format == 32 && count == 1) { server = (int)*(const unsigned long *)value; }
        XFree(value);
    }
    return server;
}

/* Gamescope numbers its servers' displays in a row from the first. */
static void gamescopeEnter(void) {
    static bool tried;
    if (tried) { return; }
    tried = true;
    int server = gamescopeServer();
    const char *name = DisplayString(x.display);
    const char *colon = name ? strrchr(name, ':') : NULL;
    if (server < 0 || !colon) { return; }
    char first[32];
    snprintf(first, sizeof first, ":%d", atoi(colon + 1) - server);
    x.gamescope = XOpenDisplay(first);
    if (x.gamescope) {
        atexit(gamescopeLeave);
        signal(SIGTERM, gamescopeStopped);
        signal(SIGINT, gamescopeStopped);
        signal(SIGHUP, gamescopeStopped);
    }
}

static bool x11Activate(const char *title) {
    Window window = named(x.root, title, 1);
    if (window == None) { return false; }
    gamescopeEnter();
    if (x.gamescope) {
        /* Gamescope gives the keyboard itself, in its own time: the window
         * is active once it has it. */
        unsigned long app = GAMESCOPE_APP;
        Window focused = None;
        int revert = 0;
        XChangeProperty(x.display, window, XInternAtom(x.display, "STEAM_GAME", False), XA_CARDINAL, 32, PropModeReplace, (const unsigned char *)&app, 1);
        gamescopeList(true);
        flush();
        XGetInputFocus(x.display, &focused, &revert);
        return focused == window;
    }
    XRaiseWindow(x.display, window);
    XSetInputFocus(x.display, window, RevertToParent, CurrentTime);
    return flush();
}

/* With no window manager nothing gives a new window the keyboard: the
 * window in front is the last one mapped, the top of the root's stack. */
static bool x11Front(void) {
    Window root = None;
    Window parent = None;
    Window *children = NULL;
    unsigned int count = 0;
    Window front = None;
    if (!XQueryTree(x.display, x.root, &root, &parent, &children, &count)) { return false; }
    for (unsigned int index = count; index > 0 && front == None; index--) {
        XWindowAttributes attributes;
        if (XGetWindowAttributes(x.display, children[index - 1], &attributes) && attributes.map_state == IsViewable && !attributes.override_redirect && attributes.class == InputOutput) { front = children[index - 1]; }
    }
    if (children) { XFree(children); }
    if (front == None) { return false; }
    if (x.gamescope) {
        /* Gamescope shows and focuses the windows of the application at the head of its list. */
        unsigned long app = GAMESCOPE_APP;
        XChangeProperty(x.display, front, XInternAtom(x.display, "STEAM_GAME", False), XA_CARDINAL, 32, PropModeReplace, (const unsigned char *)&app, 1);
        return flush();
    }
    XSetInputFocus(x.display, front, RevertToParent, CurrentTime);
    return flush();
}

static bool x11Close(const char *title) {
    Window window = named(x.root, title, 1);
    if (window == None) { return false; }
    XEvent event;
    memset(&event, 0, sizeof event);
    event.xclient.type = ClientMessage;
    event.xclient.window = window;
    event.xclient.message_type = XInternAtom(x.display, "WM_PROTOCOLS", False);
    event.xclient.format = 32;
    event.xclient.data.l[0] = (long)XInternAtom(x.display, "WM_DELETE_WINDOW", False);
    event.xclient.data.l[1] = CurrentTime;
    XSendEvent(x.display, window, False, NoEventMask, &event);
    return flush();
}

static bool x11Origin(const char *title, double *px, double *py) {
    Window window = named(x.root, title, 1);
    Window child = None;
    int left = 0;
    int top = 0;
    if (window == None || !XTranslateCoordinates(x.display, window, x.root, 0, 0, &left, &top, &child)) { return false; }
    *px = left;
    *py = top;
    return true;
}

static void x11Extent(double *width, double *height) {
    *width = DisplayWidth(x.display, DefaultScreen(x.display));
    *height = DisplayHeight(x.display, DefaultScreen(x.display));
}

/* Gamescope's session shows one application at a time and makes its new
 * window the size of the screen; the window may then ask for another. */
static bool x11FillsScreen(void) { return gamescopeServer() >= 0; }

static const RealInput x11Input = {
    .move = x11Move, .button = x11Button, .wheel = x11Wheel, .key = x11Key, .text = x11Text,
    .activate = x11Activate, .close = x11Close, .origin = x11Origin, .extent = x11Extent,
    .fillsScreen = x11FillsScreen, .front = x11Front,
};

const RealInput *realInputX11(void) {
    if (x.display) { return x.root ? &x11Input : NULL; }
    x.display = XOpenDisplay(NULL);
    if (!x.display) { return NULL; }
    int event = 0;
    int error = 0;
    int major = 0;
    int minor = 0;
    if (!XTestQueryExtension(x.display, &event, &error, &major, &minor)) { return NULL; }
    x.root = DefaultRootWindow(x.display);
    int lowest = 0;
    int highest = 0;
    int perCode = 0;
    XDisplayKeycodes(x.display, &lowest, &highest);
    KeySym *symbols = XGetKeyboardMapping(x.display, (KeyCode)lowest, highest - lowest + 1, &perCode);
    for (int code = highest; symbols && code >= lowest && !x.spare; code--) {
        bool unused = true;
        for (int level = 0; level < perCode; level++) { if (symbols[(code - lowest) * perCode + level] != NoSymbol) { unused = false; } }
        if (unused) { x.spare = (KeyCode)code; }
    }
    if (symbols) { XFree(symbols); }
    return &x11Input;
}
