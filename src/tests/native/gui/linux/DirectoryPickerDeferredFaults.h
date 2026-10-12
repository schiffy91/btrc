#ifndef DIRECTORY_PICKER_DEFERRED_FAULTS_H
#define DIRECTORY_PICKER_DEFERRED_FAULTS_H

#include <SDL3/SDL.h>
#include <stdlib.h>

void pickerDeferredShow(SDL_FileDialogType type, SDL_DialogFileCallback callback,
                        void* userdata, SDL_PropertiesID properties);
void pickerObservedFree(void* memory);

/* Only the generated program receives this header. The companion C unit
 * forwards every free unchanged and calls the production dialog callback. */
#define SDL_ShowFileDialogWithProperties pickerDeferredShow
#define free pickerObservedFree

#endif
