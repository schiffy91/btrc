#ifndef CLIPBOARD_READ_FAULTS_H
#define CLIPBOARD_READ_FAULTS_H

/* No includes: the generated unit sets its feature macros before the real
 * SDK headers declare these renamed functions with their actual signatures. */
#define SDL_HasClipboardText clipboardReadHas
#define SDL_GetClipboardText clipboardReadGet
#define SDL_free clipboardReadFree

#endif
