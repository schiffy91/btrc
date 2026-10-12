#include "ApplicationQuitProbe.h"
#include <SDL3/SDL.h>
int ui2PushApplicationQuit(void) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_QUIT;
    return SDL_PushEvent(&event) ? 1 : 0;
}
