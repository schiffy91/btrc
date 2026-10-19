/* Win32 for the Windows GUI provider. The manifest binds user32, gdi32,
 * comctl32 and kernel32 declarations directly; this header keeps only what
 * the typed importer cannot express, each for its stated reason:
 * - MsgWaitForMultipleObjectsEx takes CONST HANDLE*, a pointer to a const
 *   pointer, which the importer refuses as a lossy projection, so
 *   btrcWin32WaitForInput passes the loop's one wake event by address. */
#ifndef BTRC_GUI_WINDOWS_WIN32_H
#define BTRC_GUI_WINDOWS_WIN32_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>

/* Wait for the wake event, any queued input or the timeout. MWMO_INPUTAVAILABLE
 * returns at once for input an earlier turn saw but left queued, so a bounded
 * dispatch batch never strands the remainder. */
static inline DWORD btrcWin32WaitForInput(HANDLE wake, DWORD milliseconds) {
	return MsgWaitForMultipleObjectsEx(1u, &wake, milliseconds, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
}

#endif
