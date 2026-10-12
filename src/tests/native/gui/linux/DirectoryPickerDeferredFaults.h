#ifndef DIRECTORY_PICKER_DEFERRED_FAULTS_H
#define DIRECTORY_PICKER_DEFERRED_FAULTS_H

/* Only the generated program receives these renames. Do not include system
 * headers here: its feature-test macros must precede their first inclusion.
 * The actual SDL/libc headers declare the renamed functions with their exact
 * signatures and attributes. The companion C unit forwards every free and
 * invokes the production dialog callback without these renames. */
#define SDL_ShowFileDialogWithProperties pickerDeferredShow
#define free pickerObservedFree

#endif
