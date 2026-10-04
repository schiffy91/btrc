#include "ShellProbe.h"
#include "GUI/Linux/SDL.h"
#include <assert.h>
#include <stdio.h>

static SDL_Window *window(void) {
    int count = 0;
    SDL_Window **windows = SDL_GetWindows(&count);
    assert(count == 1);
    SDL_Window *result = windows[0];
    SDL_free(windows);
    return result;
}
static unsigned int windowId(void) { return SDL_GetWindowID(window()); }
void shellProbeClick(double x, double y) {
    unsigned int id = windowId();
    btrcSdlPushPointerMotion(id, (float)x, (float)y);
    btrcSdlPushPointerButton(id, (float)x, (float)y, 1u, 1, 1u);
    btrcSdlPushPointerButton(id, (float)x, (float)y, 1u, 0, 1u);
}
static void key(unsigned int scan, unsigned int code) {
    unsigned int id = windowId();
    btrcSdlPushKey(id, scan, code, 0u, 1, 0);
    btrcSdlPushKey(id, scan, code, 0u, 0, 0);
}
void shellProbeTab(void) { key(SDL_SCANCODE_TAB, SDLK_TAB); }
void shellProbeEnter(void) { key(SDL_SCANCODE_RETURN, SDLK_RETURN); }
void shellProbeText(void) {
    /* The provider's header-local text ring belongs to its generated TU.
     * This separate probe TU instead keeps immutable input alive for the
     * entire process, without borrowing or resetting the provider's ring. */
    SDL_Event event = {0};
    event.type = SDL_EVENT_TEXT_INPUT;
    event.text.windowID = windowId();
    event.text.text = "draft";
    assert(SDL_PushEvent(&event));
}
void shellProbeScroll(void) { btrcSdlPushWheel(windowId(), 100.0f, 120.0f, 0.0f, -3.0f); }
void shellProbeClose(void) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window.windowID = windowId();
    assert(SDL_PushEvent(&event));
}
int shellProbeFocus(void) { return SDL_TextInputActive(window()) ? 1 : 0; }
int shellProbeNativeCount(void) {
    int count = 0;
    SDL_Window **windows = SDL_GetWindows(&count);
    SDL_free(windows);
    return count;
}
void shellProbeObserve(void) { assert(shellProbeNativeCount() == 1); }
void shellProbeDump(void) {
    printf("{\"probe\":\"linux-sdl\",\"accessibility\":\"no bridge\",\"native_windows\":%d,\"focused_editor\":%d}\n",
           shellProbeNativeCount(), shellProbeFocus());
}
