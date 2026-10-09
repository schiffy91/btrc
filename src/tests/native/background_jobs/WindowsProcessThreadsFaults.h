#ifndef BTRC_TEST_WINDOWS_PROCESS_THREADS_FAULTS_H
#define BTRC_TEST_WINDOWS_PROCESS_THREADS_FAULTS_H
#include <windows.h>
#include <tlhelp32.h>

/* Forced into the generated C only. The separately compiled probe uses the
 * real SDK calls and owns every actual snapshot and thread/process handle. */
HANDLE WINAPI process_threads_snapshot(DWORD flags, DWORD process);
BOOL WINAPI process_threads_first(HANDLE snapshot, LPTHREADENTRY32 entry);
BOOL WINAPI process_threads_next(HANDLE snapshot, LPTHREADENTRY32 entry);
BOOL WINAPI process_threads_close(HANDLE snapshot);
#define CreateToolhelp32Snapshot process_threads_snapshot
#define Thread32First process_threads_first
#define Thread32Next process_threads_next
#define CloseHandle process_threads_close
#endif
