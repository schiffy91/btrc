#ifndef BTRC_SHELL_MESSAGE_TRACE_H
#define BTRC_SHELL_MESSAGE_TRACE_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

/* Forced into the diagnostic build's native units only. These wrappers call
 * the real APIs and preserve their return values and last-error state. */
BOOL WINAPI btrcShellPeekMessageW(LPMSG message, HWND window, UINT first, UINT last, UINT remove);
BOOL WINAPI btrcShellTranslateMessage(const MSG *message);
LRESULT WINAPI btrcShellDispatchMessageW(const MSG *message);

#ifndef BTRC_SHELL_MESSAGE_TRACE_IMPLEMENTATION
#define PeekMessageW btrcShellPeekMessageW
#define TranslateMessage btrcShellTranslateMessage
#define DispatchMessageW btrcShellDispatchMessageW
#endif

#endif
