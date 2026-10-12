#include "ClipboardReadControl.h"
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>

static int armed;
static int mode;
static int queries;
static int available;
static int reads;
static int allocations;
static int releases;
static int attempts;
static int totalReads;
static int totalAllocations;
static int totalReleases;
static void *outstanding;

void clipboardReadArm(int requested) {
    if (armed || outstanding != NULL || requested < 0 || requested > 3) { abort(); }
    if (attempts == 0) {
        const char *backend = SDL_GetCurrentVideoDriver();
        fprintf(stderr, "clipboard backend=%s\n", backend != NULL ? backend : "none");
    }
    armed = 1;
    mode = requested;
    queries = available = reads = allocations = releases = 0;
}

bool SDLCALL clipboardReadHas(void) {
    bool result = SDL_HasClipboardText();
    if (armed) {
        queries++;
        available += result ? 1 : 0;
    }
    return result;
}

char *SDLCALL clipboardReadGet(void) {
    if (!armed) { return SDL_GetClipboardText(); }
    if (outstanding != NULL) { abort(); }
    reads++;
    totalReads++;
    char *result;
    if (mode == 0) {
        result = SDL_strdup("");
        (void)SDL_SetError("injected clipboard read failure");
    } else if (mode == 1) {
        /* The clipboard became empty after the successful availability query. */
        result = SDL_strdup("");
        SDL_ClearError();
    } else if (mode == 2) {
        result = NULL;
        (void)SDL_SetError("injected null clipboard result");
    } else {
        result = SDL_GetClipboardText();
        /* SDL errors persist independently of later successful operations. */
        (void)SDL_SetError("unrelated stale SDL error");
    }
    if (mode != 2 && result == NULL) { abort(); }
    if (result != NULL) {
        outstanding = result;
        allocations++;
        totalAllocations++;
    }
    return result;
}

void SDLCALL clipboardReadFree(void *memory) {
    if (memory != NULL && memory == outstanding) {
        outstanding = NULL;
        releases++;
        totalReleases++;
    }
    SDL_free(memory);
}

int clipboardReadFinish(int allocationExpected) {
    int valid = armed && queries == 1 && available == 1 && reads == 1 &&
        allocations == allocationExpected && releases == allocationExpected && outstanding == NULL;
    if (!valid) {
        fprintf(stderr, "clipboard ownership: mode=%d query=%d available=%d read=%d allocated=%d freed=%d outstanding=%d\n",
                mode, queries, available, reads, allocations, releases, outstanding != NULL);
    }
    armed = 0;
    attempts++;
    return valid;
}

int clipboardReadComplete(void) {
    fprintf(stderr, "clipboard ledger: attempts=%d reads=%d allocations=%d frees=%d outstanding=%d\n",
            attempts, totalReads, totalAllocations, totalReleases, outstanding != NULL);
    return !armed && outstanding == NULL && attempts == 300 && totalReads == 300 &&
        totalAllocations == totalReleases;
}
