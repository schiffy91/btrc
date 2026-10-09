#ifndef BTRC_WINDOWS_PROCESS_THREADS_H
#define BTRC_WINDOWS_PROCESS_THREADS_H

#include <windows.h>
#include <tlhelp32.h>
#include <limits.h>
#include <stddef.h>

/* Derive the last byte needed for ownership filtering from the selected SDK. */
enum BtrcThreadEntryExtent {
    BTRC_THREAD_OWNER_END = offsetof(THREADENTRY32, th32OwnerProcessID)
        + sizeof(((THREADENTRY32 *)0)->th32OwnerProcessID)
};

#endif
