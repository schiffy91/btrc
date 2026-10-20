#include "EventBoundary.h"
#include <SDL3/SDL.h>
#include <webgpu.h>
#include <stdlib.h>

static unsigned int target;
static int latest;
static int frames;
static int admitted;
static int rejected;
static bool armed;

/* Observe successful native presentation without changing the GPU result. */
WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result == WGPUStatus_Success) { frames++; }
    return result;
}

int eventBoundaryFrames(void) { return frames; }

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

bool __real_SDL_PushEvent(SDL_Event *event);
bool __wrap_SDL_PushEvent(SDL_Event *event) {
    bool relevant = armed && accepted(NULL, event);
    bool result = __real_SDL_PushEvent(event);
    if (relevant) { if (result) { admitted++; } else { rejected++; } }
    return result;
}
int eventBoundaryAccepted(void) { return admitted; }
int eventBoundaryRejected(void) { return rejected; }

void eventBoundaryArm(unsigned int window) {
    target = window;
    admitted = rejected = 0;
    armed = true;
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
    bool pushed = SDL_PushEvent(&event);
    if (!pushed) { abort(); }
}

void eventBoundaryDisarm(void) { armed = false; SDL_SetEventFilter(NULL, NULL); }
