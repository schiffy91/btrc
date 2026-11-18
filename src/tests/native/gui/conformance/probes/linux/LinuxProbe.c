/* The conformance probe for Linux. While the GTK provider is built beside the
 * SDL one (docs/design/native-ui-surfaces-and-hosts.md, section 3) one probe
 * serves both. A window the GTK provider made gets real input through the
 * display server (GtkProbe.c). A window the SDL provider made gets synthetic
 * SDL events, a stand-in that goes when that provider does. */
#include "../ConformanceProbe.h"
#include "GtkProbe.h"
#include <SDL3/SDL.h>
#include <stdlib.h>
#include <string.h>

/* The GTK shim's name for a window (GUI/Linux/Gtk/GtkShim.h). A program
 * built on the SDL provider does not link the shim, so it is weak and absent
 * there. */
unsigned int btrcGtkWindowNamed(const char *title) __attribute__((weak));

static unsigned int gtkWindowNamed(const char *title) { return btrcGtkWindowNamed ? btrcGtkWindowNamed(title) : 0; }

static SDL_WindowID windowNamed(const char *title) {
    int count = 0;
    SDL_Window **windows = SDL_GetWindows(&count);
    SDL_WindowID found = 0;
    for (int index = 0; windows && index < count; index++) {
        const char *candidate = SDL_GetWindowTitle(windows[index]);
        if (candidate && strcmp(candidate, title) == 0) {
            found = SDL_GetWindowID(windows[index]);
            break;
        }
    }
    SDL_free(windows);
    return found;
}

static int button(const char *title, double x, double y, bool down) {
    unsigned int native = gtkWindowNamed(title);
    if (native) { return gtkProbeButton(native, title, x, y, down ? 1 : 0); }
    SDL_WindowID window = windowNamed(title);
    if (!window) { return 0; }
    SDL_Event event;
    memset(&event, 0, sizeof event);
    event.type = down ? SDL_EVENT_MOUSE_BUTTON_DOWN : SDL_EVENT_MOUSE_BUTTON_UP;
    event.button.windowID = window;
    event.button.x = (float)x;
    event.button.y = (float)y;
    event.button.button = SDL_BUTTON_LEFT;
    event.button.clicks = 1;
    event.button.down = down;
    return SDL_PushEvent(&event) ? 1 : 0;
}

int conformanceProbeMove(const char *title, double x, double y) {
    unsigned int native = gtkWindowNamed(title);
    if (native) { return gtkProbeMove(native, title, x, y); }
    SDL_WindowID window = windowNamed(title);
    if (!window) { return 0; }
    SDL_Event event;
    memset(&event, 0, sizeof event);
    event.type = SDL_EVENT_MOUSE_MOTION;
    event.motion.windowID = window;
    event.motion.x = (float)x;
    event.motion.y = (float)y;
    return SDL_PushEvent(&event) ? 1 : 0;
}

int conformanceProbePress(const char *title, double x, double y) { return button(title, x, y, true); }

int conformanceProbeRelease(const char *title, double x, double y) { return button(title, x, y, false); }

int conformanceProbeWheel(const char *title, double x, double y, double deltaX, double deltaY) {
    unsigned int native = gtkWindowNamed(title);
    if (native) { return gtkProbeWheel(native, title, x, y, deltaX, deltaY); }
    SDL_WindowID window = windowNamed(title);
    if (!window) { return 0; }
    SDL_Event event;
    memset(&event, 0, sizeof event);
    event.type = SDL_EVENT_MOUSE_WHEEL;
    event.wheel.windowID = window;
    event.wheel.mouse_x = (float)x;
    event.wheel.mouse_y = (float)y;
    event.wheel.x = (float)deltaX;
    event.wheel.y = (float)deltaY;
    return SDL_PushEvent(&event) ? 1 : 0;
}

int conformanceProbeKey(const char *title, int key) {
    static const struct { SDL_Scancode scancode; SDL_Keycode keycode; SDL_Keymod modifiers; } keys[] = {
        [CONFORMANCE_KEY_RETURN] = {SDL_SCANCODE_RETURN, SDLK_RETURN, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_ESCAPE] = {SDL_SCANCODE_ESCAPE, SDLK_ESCAPE, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_TAB] = {SDL_SCANCODE_TAB, SDLK_TAB, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_LEFT] = {SDL_SCANCODE_LEFT, SDLK_LEFT, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_RIGHT] = {SDL_SCANCODE_RIGHT, SDLK_RIGHT, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_UP] = {SDL_SCANCODE_UP, SDLK_UP, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_DOWN] = {SDL_SCANCODE_DOWN, SDLK_DOWN, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_BACKSPACE] = {SDL_SCANCODE_BACKSPACE, SDLK_BACKSPACE, SDL_KMOD_NONE},
        [CONFORMANCE_KEY_SELECT_ALL] = {SDL_SCANCODE_A, SDLK_A, SDL_KMOD_CTRL},
    };
    if (key < CONFORMANCE_KEY_RETURN || key > CONFORMANCE_KEY_SELECT_ALL) { return 0; }
    unsigned int native = gtkWindowNamed(title);
    if (native) { return gtkProbeKey(native, title, key); }
    SDL_WindowID window = windowNamed(title);
    if (!window) { return 0; }
    for (int down = 1; down >= 0; down--) {
        SDL_Event event;
        memset(&event, 0, sizeof event);
        event.type = down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
        event.key.windowID = window;
        event.key.scancode = keys[key].scancode;
        event.key.key = keys[key].keycode;
        event.key.mod = keys[key].modifiers;
        event.key.down = down != 0;
        if (!SDL_PushEvent(&event)) { return 0; }
    }
    return 1;
}

/* SDL's text event borrows its bytes until the event is handled, so each
 * queued text keeps its own copy for the life of the process: a test's few
 * short strings, never freed while an event could still name them. */
int conformanceProbeText(const char *title, const char *text) {
    unsigned int native = gtkWindowNamed(title);
    if (native) { return gtkProbeText(native, title, text); }
    SDL_WindowID window = windowNamed(title);
    if (!window) { return 0; }
    size_t length = strlen(text) + 1;
    char *kept = malloc(length);
    if (!kept) { return 0; }
    memcpy(kept, text, length);
    SDL_Event event;
    memset(&event, 0, sizeof event);
    event.type = SDL_EVENT_TEXT_INPUT;
    event.text.windowID = window;
    event.text.text = kept;
    return SDL_PushEvent(&event) ? 1 : 0;
}

int conformanceProbeClose(const char *title) {
    unsigned int native = gtkWindowNamed(title);
    if (native) { return gtkProbeClose(native, title); }
    SDL_WindowID window = windowNamed(title);
    if (!window) { return 0; }
    SDL_Event event;
    memset(&event, 0, sizeof event);
    event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window.windowID = window;
    return SDL_PushEvent(&event) ? 1 : 0;
}
