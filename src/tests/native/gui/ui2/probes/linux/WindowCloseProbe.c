#include "WindowCloseProbe.h"
#include <SDL3/SDL.h>
int ui2PushWindowClose(unsigned int window) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window.windowID = window;
    return SDL_PushEvent(&event) ? 1 : 0;
}

int ui2PushQuit(void) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_QUIT;
    return SDL_PushEvent(&event) ? 1 : 0;
}

int ui2PushPointerMotion(unsigned int window) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_MOUSE_MOTION;
    event.motion.windowID = window;
    event.motion.x = 5.0f;
    event.motion.y = 5.0f;
    return SDL_PushEvent(&event) ? 1 : 0;
}
