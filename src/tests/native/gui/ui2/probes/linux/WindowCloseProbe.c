#include "WindowCloseProbe.h"
#include <SDL3/SDL.h>
int ui2PushWindowClose(unsigned int window) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window.windowID = window;
    return SDL_PushEvent(&event) ? 1 : 0;
}
