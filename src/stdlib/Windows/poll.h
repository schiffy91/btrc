#ifndef BTRC_WIN_POLL_H
#define BTRC_WIN_POLL_H

/* MinGW-w64 has no POSIX poll(2) header.  This file intentionally provides no
 * API: it lets orphaned includes survive after process/terminal dead-code
 * elimination, while a program that actually uses pollfd or poll() still
 * fails at compile time until the Win32 backend is selected. */

#endif
