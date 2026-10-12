#include "WindowsProcessThreadsProbe.h"
#include <windows.h>
#include <tlhelp32.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* All waits are bounded. A foreign child watches the exact parent process,
 * so an assertion/fatal exit in the parent does not strand it. */
static HANDLE release_threads;
static HANDLE ready_threads[3];
static HANDLE held_threads[3];
static HANDLE foreign_process, foreign_release, foreign_ready;
static DWORD foreign_pid;
static int fault, snapshots, closes, next_calls, bad_sizes, foreign_seen;
static HANDLE live_snapshot;

static void require(int condition, const char *message) {
    if (!condition) {
        fprintf(stderr, "WindowsProcessThreads probe: %s (error %lu)\n", message, (unsigned long)GetLastError());
        ExitProcess(90);
    }
}

static DWORD WINAPI held_thread(void *ready) {
    if (!SetEvent((HANDLE)ready)) { return 1; }
    return WaitForSingleObject(release_threads, 15000) == WAIT_OBJECT_0 ? 0 : 1;
}

void process_threads_start_held(void) {
    require(release_threads == NULL, "held threads already active");
    release_threads = CreateEventW(NULL, TRUE, FALSE, NULL);
    require(release_threads != NULL, "create thread release event");
    for (int i = 0; i < 3; i++) {
        ready_threads[i] = CreateEventW(NULL, TRUE, FALSE, NULL);
        require(ready_threads[i] != NULL, "create thread ready event");
        held_threads[i] = CreateThread(NULL, 0, held_thread, ready_threads[i], 0, NULL);
        require(held_threads[i] != NULL, "create held thread");
    }
    require(WaitForMultipleObjects(3, ready_threads, TRUE, 5000) == WAIT_OBJECT_0, "held threads ready");
}

void process_threads_stop_held(void) {
    require(release_threads != NULL && SetEvent(release_threads), "release held threads");
    require(WaitForMultipleObjects(3, held_threads, TRUE, 5000) == WAIT_OBJECT_0, "join held threads");
    for (int i = 0; i < 3; i++) {
        DWORD status = 1;
        require(GetExitCodeThread(held_threads[i], &status) && status == 0, "held thread status");
        require(CloseHandle(held_threads[i]) && CloseHandle(ready_threads[i]), "close held thread handles");
        held_threads[i] = ready_threads[i] = NULL;
    }
    require(CloseHandle(release_threads), "close thread release event");
    release_threads = NULL;
}

int process_threads_child_mode(int argc, char **argv) {
    if (argc < 2 || strcmp(argv[1], "--process-threads-child") != 0) { return -1; }
    require(argc == 5, "child arguments");
    HANDLE release = (HANDLE)(uintptr_t)strtoull(argv[2], NULL, 10);
    HANDLE ready = (HANDLE)(uintptr_t)strtoull(argv[3], NULL, 10);
    DWORD parent_pid = (DWORD)strtoul(argv[4], NULL, 10);
    HANDLE parent = OpenProcess(SYNCHRONIZE, FALSE, parent_pid);
    if (parent == NULL) { return 1; }
    process_threads_start_held();
    require(SetEvent(ready), "foreign ready");
    HANDLE waiting[2] = { release, parent };
    DWORD waited = WaitForMultipleObjects(2, waiting, FALSE, 10000);
    process_threads_stop_held();
    require(CloseHandle(parent) && CloseHandle(release) && CloseHandle(ready), "close foreign inherited handles");
    return waited == WAIT_OBJECT_0 || waited == WAIT_OBJECT_0 + 1 ? 0 : 1;
}

void process_threads_start_foreign(void) {
    require(foreign_process == NULL, "foreign process already active");
    SECURITY_ATTRIBUTES attributes = { sizeof(SECURITY_ATTRIBUTES), NULL, TRUE };
    foreign_release = CreateEventW(&attributes, TRUE, FALSE, NULL);
    foreign_ready = CreateEventW(&attributes, TRUE, FALSE, NULL);
    require(foreign_release != NULL && foreign_ready != NULL, "create foreign events");
    wchar_t image[32768], command[33000];
    DWORD length = GetModuleFileNameW(NULL, image, 32768);
    require(length > 0 && length < 32768, "current executable path");
    int size = swprintf(command, 33000, L"\"%ls\" --process-threads-child %llu %llu %lu", image,
        (unsigned long long)(uintptr_t)foreign_release, (unsigned long long)(uintptr_t)foreign_ready,
        (unsigned long)GetCurrentProcessId());
    require(size > 0 && size < 33000, "foreign command length");
    STARTUPINFOW startup = { 0 };
    PROCESS_INFORMATION created = { 0 };
    startup.cb = sizeof(startup);
    require(CreateProcessW(image, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &created), "create foreign process");
    foreign_process = created.hProcess;
    foreign_pid = created.dwProcessId;
    require(CloseHandle(created.hThread), "close foreign primary thread handle");
    HANDLE waiting[2] = { foreign_ready, foreign_process };
    require(WaitForMultipleObjects(2, waiting, FALSE, 5000) == WAIT_OBJECT_0, "foreign threads ready");
}

void process_threads_stop_foreign(void) {
    require(foreign_process != NULL && SetEvent(foreign_release), "release foreign process");
    DWORD waited = WaitForSingleObject(foreign_process, 5000);
    if (waited != WAIT_OBJECT_0) {
        require(TerminateProcess(foreign_process, 91), "terminate timed-out owned child");
        require(WaitForSingleObject(foreign_process, 5000) == WAIT_OBJECT_0, "reap timed-out owned child");
    }
    DWORD status = 1;
    require(GetExitCodeProcess(foreign_process, &status), "foreign exit status");
    require(CloseHandle(foreign_process) && CloseHandle(foreign_ready) && CloseHandle(foreign_release), "close foreign handles");
    foreign_process = foreign_ready = foreign_release = NULL;
    foreign_pid = 0;
    require(waited == WAIT_OBJECT_0 && status == 0, "foreign clean exit");
}

void process_threads_reset(int selected) {
    require(live_snapshot == NULL, "previous snapshot leaked");
    fault = selected;
    snapshots = closes = next_calls = bad_sizes = foreign_seen = 0;
}
int process_threads_snapshots(void) { return snapshots; }
int process_threads_closes(void) { return closes; }
int process_threads_next_calls(void) { return next_calls; }
int process_threads_bad_sizes(void) { return bad_sizes; }
int process_threads_live_snapshots(void) { return live_snapshot != NULL; }
int process_threads_foreign_seen(void) { return foreign_seen; }

HANDLE WINAPI process_threads_snapshot(DWORD flags, DWORD process) {
    snapshots++;
    require(flags == TH32CS_SNAPTHREAD && process == 0 && live_snapshot == NULL, "snapshot arguments/ownership");
    if (fault == PROCESS_THREADS_SNAPSHOT_FAILURE) {
        SetLastError(ERROR_ACCESS_DENIED);
        return INVALID_HANDLE_VALUE;
    }
    HANDLE snapshot = CreateToolhelp32Snapshot(flags, process);
    require(snapshot != INVALID_HANDLE_VALUE, "real snapshot creation");
    live_snapshot = snapshot;
    return snapshot;
}

static BOOL alter_entry(BOOL found, LPTHREADENTRY32 entry, int first) {
    if (!found) { return found; }
    require(entry->dwSize >= offsetof(THREADENTRY32, th32OwnerProcessID) + sizeof(entry->th32OwnerProcessID), "real SDK owner field unavailable");
    if (foreign_pid != 0 && entry->th32OwnerProcessID == foreign_pid) { foreign_seen++; }
    if ((first && fault == PROCESS_THREADS_SHORT_FIRST) || (!first && fault == PROCESS_THREADS_SHORT_NEXT)) {
        entry->dwSize = offsetof(THREADENTRY32, th32OwnerProcessID);
        /* A provider that filters PID before validating size would skip this
         * deliberately foreign short record and continue, violating the oracle. */
        entry->th32OwnerProcessID = GetCurrentProcessId() ^ 1;
    } else if (fault == PROCESS_THREADS_SHORT_VALID) {
        entry->dwSize = offsetof(THREADENTRY32, th32OwnerProcessID) + sizeof(entry->th32OwnerProcessID);
    } else if (fault == PROCESS_THREADS_FOREIGN_ONLY) {
        entry->th32OwnerProcessID = GetCurrentProcessId() ^ 1;
    }
    return found;
}

BOOL WINAPI process_threads_first(HANDLE snapshot, LPTHREADENTRY32 entry) {
    require(snapshot == live_snapshot, "first snapshot ownership");
    if (entry->dwSize != sizeof(*entry)) { bad_sizes++; SetLastError(ERROR_BAD_LENGTH); return FALSE; }
    if (fault == PROCESS_THREADS_FIRST_FAILURE || fault == PROCESS_THREADS_EMPTY) {
        SetLastError(fault == PROCESS_THREADS_EMPTY ? ERROR_NO_MORE_FILES : ERROR_ACCESS_DENIED);
        return FALSE;
    }
    return alter_entry(Thread32First(snapshot, entry), entry, 1);
}

BOOL WINAPI process_threads_next(HANDLE snapshot, LPTHREADENTRY32 entry) {
    next_calls++;
    require(snapshot == live_snapshot, "next snapshot ownership");
    if (entry->dwSize != sizeof(*entry)) { bad_sizes++; SetLastError(ERROR_BAD_LENGTH); return FALSE; }
    if (fault == PROCESS_THREADS_NEXT_FAILURE) { SetLastError(ERROR_ACCESS_DENIED); return FALSE; }
    BOOL found = Thread32Next(snapshot, entry);
    if (fault == PROCESS_THREADS_SHORT_NEXT) { require(found, "real second snapshot entry required"); }
    return alter_entry(found, entry, 0);
}

BOOL WINAPI process_threads_close(HANDLE snapshot) {
    closes++;
    require(snapshot == live_snapshot && live_snapshot != NULL, "exact single snapshot close");
    require(CloseHandle(snapshot), "real snapshot close");
    live_snapshot = NULL;
    /* Even success may overwrite last error. Provider must save EOF/error first. */
    SetLastError(ERROR_INVALID_DATA);
    return fault == PROCESS_THREADS_CLOSE_FAILURE ? FALSE : TRUE;
}
