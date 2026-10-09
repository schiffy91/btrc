#include "InputRepair.h"
#include <SDL3/SDL.h>
#include <webgpu.h>
#include <stdlib.h>
#include <string.h>

static int failClipboard;
static int clipboardWrites;
static int frames;

bool __real_SDL_SetClipboardText(const char *text);
bool __wrap_SDL_SetClipboardText(const char *text) {
    clipboardWrites++;
    if (failClipboard) { return SDL_SetError("injected clipboard publication failure"); }
    return __real_SDL_SetClipboardText(text);
}

void inputFailClipboard(int fail) { failClipboard = fail; }
int inputClipboardWrites(void) { return clipboardWrites; }
int inputClipboardMatches(int value) {
    char *text = SDL_GetClipboardText();
    int matches = text != NULL && strcmp(text, value == 0 ? "seed" : "alpha") == 0;
    SDL_free(text);
    return matches;
}

WGPUStatus __real_wgpuSurfacePresent(WGPUSurface surface);
WGPUStatus __wrap_wgpuSurfacePresent(WGPUSurface surface) {
    WGPUStatus result = __real_wgpuSurfacePresent(surface);
    if (result == WGPUStatus_Success) { frames++; }
    return result;
}
int inputFrames(void) { return frames; }

/* Use SDL itself, bypassing the BTRC window's show/hide methods. */
void inputVisibility(unsigned int id, int shown) {
    SDL_Window *window = SDL_GetWindowFromID(id);
    if (window == NULL || !(shown ? SDL_ShowWindow(window) : SDL_HideWindow(window))) { abort(); }
}
