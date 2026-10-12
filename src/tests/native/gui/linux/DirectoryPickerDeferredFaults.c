#include "DirectoryPickerDeferredControl.h"
#include <GUI/Linux/SDL.h>
#include <assert.h>

static SDL_Mutex* pickerLock;
static SDL_Semaphore* pickerRelease;
static SDL_Thread* pickerThread;
static BtrcSdlFolderDialog* pickerDialog;
static SDL_DialogFileCallback pickerCallback;
static void* pickerUserdata;
static int pickerMode;
static int pickerOpens;
static int pickerFrees;
static SDL_AtomicInt pickerCallbacks;
static SDL_AtomicInt pickerCallbackReferences;
static SDL_AtomicInt pickerFallbacks;
static SDL_AtomicInt pickerResult;

static void pickerDeliver(int result) {
    const char* selected[] = {"/test/selected-directory", NULL};
    const char* empty[] = {"", NULL};
    const char* dismissed[] = {NULL};
    SDL_LockMutex(pickerLock);
    assert(pickerDialog != NULL);
    SDL_SetAtomicInt(&pickerCallbackReferences, SDL_GetAtomicInt(&pickerDialog->owners));
    SDL_UnlockMutex(pickerLock);
    if (result == 3) { SDL_SetError("deliberate directory picker failure"); }
    pickerCallback(pickerUserdata, result == 1 ? selected : result == 2 ? dismissed : result == 4 ? empty : NULL, 0);
    SDL_AddAtomicInt(&pickerCallbacks, 1);
}

static int pickerWait(void* unused) {
    (void)unused;
    /* A broken picker still reaches a real terminal callback and cleans up.
     * Tests then reject its wrong outcome; timeout alone is not the oracle. */
    if (!SDL_WaitSemaphoreTimeout(pickerRelease, 5000)) { SDL_AddAtomicInt(&pickerFallbacks, 1); }
    pickerDeliver(SDL_GetAtomicInt(&pickerResult));
    return 0;
}

void pickerReset(int mode) {
    assert(pickerLock == NULL && pickerThread == NULL && pickerDialog == NULL);
    pickerLock = SDL_CreateMutex();
    assert(pickerLock != NULL);
    pickerMode = mode; pickerOpens = 0; pickerFrees = 0;
    SDL_SetAtomicInt(&pickerCallbacks, 0);
    SDL_SetAtomicInt(&pickerCallbackReferences, 0);
    SDL_SetAtomicInt(&pickerFallbacks, 0);
    SDL_SetAtomicInt(&pickerResult, 1);
}

void pickerDeferredShow(SDL_FileDialogType type, SDL_DialogFileCallback callback,
                        void* userdata, SDL_PropertiesID properties) {
    assert(type == SDL_FILEDIALOG_OPENFOLDER && properties != 0);
    assert(pickerDialog == NULL && pickerThread == NULL);
    pickerOpens++;
    pickerDialog = (BtrcSdlFolderDialog*)userdata;
    pickerCallback = callback; pickerUserdata = userdata;
    assert(SDL_GetAtomicInt(&pickerDialog->owners) == 2);
    if (pickerMode != 0) { pickerDeliver(pickerMode); return; }
    pickerRelease = SDL_CreateSemaphore(0);
    assert(pickerRelease != NULL);
    pickerThread = SDL_CreateThread(pickerWait, "picker-deferred-callback", NULL);
    assert(pickerThread != NULL);
}

void pickerObservedFree(void* memory) {
    if (pickerLock != NULL) {
        SDL_LockMutex(pickerLock);
        if (memory != NULL && memory == pickerDialog) { pickerDialog = NULL; pickerFrees++; }
        SDL_UnlockMutex(pickerLock);
    }
    free(memory);
}

void pickerComplete(int result) {
    if (pickerThread == NULL) { return; }
    SDL_SetAtomicInt(&pickerResult, result);
    SDL_SignalSemaphore(pickerRelease);
    SDL_WaitThread(pickerThread, NULL);
    pickerThread = NULL;
    SDL_DestroySemaphore(pickerRelease); pickerRelease = NULL;
}

void pickerDispose(void) {
    assert(pickerThread == NULL && pickerDialog == NULL);
    SDL_DestroyMutex(pickerLock); pickerLock = NULL;
}

int pickerOpenCount(void) { return pickerOpens; }
int pickerCallbackCount(void) { return SDL_GetAtomicInt(&pickerCallbacks); }
int pickerCallbackOwners(void) { return SDL_GetAtomicInt(&pickerCallbackReferences); }
int pickerFallbackCount(void) { return SDL_GetAtomicInt(&pickerFallbacks); }
int pickerOwners(void) {
    SDL_LockMutex(pickerLock);
    int owners = pickerDialog == NULL ? 0 : SDL_GetAtomicInt(&pickerDialog->owners);
    SDL_UnlockMutex(pickerLock);
    return owners;
}
int pickerFreeCount(void) {
    SDL_LockMutex(pickerLock);
    int count = pickerFrees;
    SDL_UnlockMutex(pickerLock);
    return count;
}
int pickerPushQuit(void) {
    SDL_Event event = {0}; event.type = SDL_EVENT_QUIT;
    return SDL_PushEvent(&event) ? 1 : 0;
}
