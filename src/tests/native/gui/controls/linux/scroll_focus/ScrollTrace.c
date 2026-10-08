/* Diagnostic link wrappers: observe successful SDL queue operations unchanged. */
#include <SDL3/SDL.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

extern bool __real_SDL_PollEvent(SDL_Event *);
extern bool __real_SDL_WaitEventTimeout(SDL_Event *, Sint32);
extern bool __real_SDL_PushEvent(SDL_Event *);

static void trace_event(const char *operation, const SDL_Event *event, bool result) {
    if (!result || event == NULL) return;
    Uint32 window = 0;
    float x = 0, y = 0;
    const char *kind = "OTHER";
    switch (event->type) {
    case SDL_EVENT_MOUSE_MOTION:
        kind = "MOTION"; window = event->motion.windowID; x = event->motion.x; y = event->motion.y; break;
    case SDL_EVENT_MOUSE_BUTTON_DOWN: case SDL_EVENT_MOUSE_BUTTON_UP:
        kind = event->type == SDL_EVENT_MOUSE_BUTTON_DOWN ? "DOWN" : "UP";
        window = event->button.windowID; x = event->button.x; y = event->button.y; break;
    case SDL_EVENT_MOUSE_WHEEL:
        kind = "WHEEL"; window = event->wheel.windowID; x = event->wheel.mouse_x; y = event->wheel.mouse_y; break;
    case SDL_EVENT_WINDOW_FOCUS_LOST: kind = "FOCUS_LOST"; window = event->window.windowID; break;
    case SDL_EVENT_WINDOW_FOCUS_GAINED: kind = "FOCUS_GAINED"; window = event->window.windowID; break;
    case SDL_EVENT_WINDOW_EXPOSED: kind = "EXPOSED"; window = event->window.windowID; break;
    case SDL_EVENT_WINDOW_RESIZED: kind = "RESIZED"; window = event->window.windowID; break;
    default: return;
    }
    SDL_Window *focus = strcmp(operation, "push") == 0 ? NULL : SDL_GetKeyboardFocus();
    Uint32 focused = focus == NULL ? 0 : SDL_GetWindowID(focus);
    fprintf(stderr, "SCROLL_EVENT pid=%ld ns=%llu op=%s type=%u kind=%s window=%u focus=%u x=%.9g y=%.9g\n",
            (long)getpid(), (unsigned long long)SDL_GetTicksNS(), operation,
            (unsigned int)event->type, kind, (unsigned int)window, (unsigned int)focused, (double)x, (double)y);
    fflush(stderr);
}
bool __wrap_SDL_PollEvent(SDL_Event *event) {
    bool result = __real_SDL_PollEvent(event);
    trace_event("poll", event, result); return result;
}
bool __wrap_SDL_WaitEventTimeout(SDL_Event *event, Sint32 timeout) {
    bool result = __real_SDL_WaitEventTimeout(event, timeout);
    trace_event("wait", event, result); return result;
}
bool __wrap_SDL_PushEvent(SDL_Event *event) {
    bool result = __real_SDL_PushEvent(event);
    trace_event("push", event, result); return result;
}
