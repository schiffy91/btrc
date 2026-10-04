#include "EventBoundary.h"
#include <SDL3/SDL.h>
#include <assert.h>

static unsigned int target;
static int latest;

/* Link-only observation: delegate every poll unchanged, preserving its result.
 * The synthetic keycode carries a unique ordinal before the provider maps it
 * into the portable key vocabulary. Delivery callbacks read that ordinal. */
bool __real_SDL_PollEvent(SDL_Event *event);
bool __wrap_SDL_PollEvent(SDL_Event *event) {
    bool result = __real_SDL_PollEvent(event);
    latest = result && event != NULL && (event->type == SDL_EVENT_KEY_DOWN || event->type == SDL_EVENT_KEY_UP)
                 ? (int)event->key.key - 65536 : 0;
    return result;
}

int eventBoundaryLatest(void) { return latest; }

/* After flushing setup traffic, isolate newly submitted target input from
 * asynchronous compositor notifications. Admitted test events are not
 * synthesized, reordered, removed or modified by the observer. */
static bool accepted(void *unused, SDL_Event *event) {
    (void)unused;
    if (event->type == SDL_EVENT_KEY_DOWN || event->type == SDL_EVENT_KEY_UP)
        return event->key.windowID == target;
    if (event->type == SDL_EVENT_TEXT_INPUT)
        return event->text.windowID == target;
    return event->type == SDL_EVENT_WINDOW_CLOSE_REQUESTED && event->window.windowID == target;
}

void eventBoundaryArm(unsigned int window) {
    target = window;
    SDL_FlushEvents(SDL_EVENT_FIRST, SDL_EVENT_LAST);
    SDL_SetEventFilter(accepted, NULL);
}

int eventBoundaryQueued(void) {
    return SDL_PeepEvents(NULL, 0, SDL_PEEKEVENT, SDL_EVENT_FIRST, SDL_EVENT_LAST);
}

void eventBoundaryClose(unsigned int window) {
    SDL_Event event = {0};
    event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window.windowID = window;
    assert(SDL_PushEvent(&event));
}

void eventBoundaryDisarm(void) { SDL_SetEventFilter(NULL, NULL); }
