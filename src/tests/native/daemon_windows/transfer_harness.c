/* Consumer side of the real image/launch/handshake/record path. The companion
 * is launch_harness.c, whose reserved entry exercises the native supervisor. */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "windows_daemon_image.h"
#include <windows.h>
#include "windows_security.h"

static int narrow(const wchar_t *wide, char *text, int capacity) {
    return WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1,
        text, capacity, NULL, NULL) != 0;
}

static int close_image(__btrc_windows_image_owner **image) {
    __btrc_windows_launch_error_t error;
    uint64_t deadline = GetTickCount64() + 5000;
    do {
        if (__btrc_windows_supervisor_image_close(image, &error) == 0) return 0;
        if (error.ownership_state != 1) break;
        Sleep(1);
    } while (GetTickCount64() < deadline);
    fprintf(stderr, "close stage=%u domain=%u code=%u ownership=%u\n",
        error.stage, error.domain, error.native_code, error.ownership_state);
    return -1;
}

static int transfer_case(const char *name, uint32_t expected, int live) {
    wchar_t temporary[1024], directory[1200], control[1300], log[1300], self[32768];
    char directory_text[4096], control_text[4096], log_text[4096], self_text[131072];
    if (!GetTempPathW(1024, temporary) || !GetModuleFileNameW(NULL, self, 32768)) return 2;
    swprintf(directory, 1200, L"%lsbtrc-transfer-api-%lu", temporary, (unsigned long)GetCurrentProcessId());
    swprintf(control, 1300, L"%ls\\worker.control", directory);
    swprintf(log, 1300, L"%ls\\worker.log", directory);
    void *descriptor = NULL;
    if (btrcWinPrivateDescriptor(1, &descriptor) != 0) return 3;
    SECURITY_ATTRIBUTES security = { sizeof(security), descriptor, FALSE };
    BOOL created = CreateDirectoryW(directory, &security);
    free(descriptor);
    if (!created || !narrow(directory, directory_text, sizeof(directory_text))
            || !narrow(control, control_text, sizeof(control_text)) || !narrow(log, log_text, sizeof(log_text))
            || !narrow(self, self_text, sizeof(self_text))) return 4;
    __btrc_windows_daemon_startup startup;
    memset(&startup, 0, sizeof(startup));
    char *arguments[] = { self_text };
    startup.command.executable_utf8 = self_text;
    startup.command.argv_utf8 = arguments; startup.command.argc = 1;
    startup.command.cwd_utf8 = directory_text;
    startup.name_utf8 = name; startup.control_path_utf8 = control_text; startup.log_path_utf8 = log_text;
    unsigned char token[16];
    memset(token, 0xA3, sizeof(token));
    __btrc_windows_image_owner *image = NULL;
    __btrc_windows_launch_error_t error;
    if (__btrc_windows_supervisor_image_verify(&image, &error) != 0) {
        fprintf(stderr, "verify stage=%u code=%u\n", error.stage, error.native_code); return 5;
    }
    __btrc_windows_transfer_result result = { 99, 99, 99 };
    if (__btrc_windows_supervisor_transfer(image, &startup, token, 0, &result, &error) == 0
            || result.state != 1 || result.supervisor_pid != 0 || result.lifetime != 0) return 6;
    if (__btrc_windows_supervisor_transfer(image, &startup, token, UINT64_MAX, &result, &error) == 0
            || result.state != 1 || result.supervisor_pid != 0) return 7;
    int status = __btrc_windows_supervisor_transfer(image, &startup, token, 5000, &result, &error);
    if ((status == 0) != (expected == 0) || result.state != expected
            || result.supervisor_pid < 2 || result.lifetime > 1) {
        fprintf(stderr, "transfer status=%d state=%u pid=%u lifetime=%u stage=%u domain=%u code=%u ownership=%u\n",
            status, result.state, result.supervisor_pid, result.lifetime,
            error.stage, error.domain, error.native_code, error.ownership_state);
        return 8;
    }
    if (close_image(&image) != 0 || image != NULL) return 9;
    HANDLE observer = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
        FALSE, result.supervisor_pid);
    if (live) {
        if (observer == NULL || WaitForSingleObject(observer, 100) != WAIT_TIMEOUT) return 10;
        if (!TerminateProcess(observer, 0)) return 11;
    }
    if (observer != NULL) {
        if (WaitForSingleObject(observer, 5000) != WAIT_OBJECT_0 || !CloseHandle(observer)) return 12;
    } else if (GetLastError() != ERROR_INVALID_PARAMETER) return 13;
    if (strcmp(name, "commit-26") == 0 && GetFileAttributesW(control) == INVALID_FILE_ATTRIBUTES) return 14;
    /* These are fixture-owned paths. Runtime cleanup must never remove a
     * replaced record, which the commit-26 case checked above. */
    if (GetFileAttributesW(control) != INVALID_FILE_ATTRIBUTES && !DeleteFileW(control)) return 15;
    if (GetFileAttributesW(log) != INVALID_FILE_ATTRIBUTES && !DeleteFileW(log)) return 16;
    if (!RemoveDirectoryW(directory)) return 17;
    SecureZeroMemory(token, sizeof(token));
    return 0;
}

#if defined(BTRC_DAEMON_FAULT_FIXTURE)
/* This fixture-only capability is linked by fault consumers. The production
 * image object and the ordinary consumer contain no reference to it. */
void btrc_daemon_fault_terminate(uint32_t supervisor_pid) {
    HANDLE process = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, FALSE, supervisor_pid);
    if (process == NULL || !TerminateProcess(process, 91)
            || WaitForSingleObject(process, 5000) != WAIT_OBJECT_0 || !CloseHandle(process)) ExitProcess(92);
}

static int commit_exit_parent(void) {
    wchar_t self[32768], invocation[32768];
    DWORD units = GetModuleFileNameW(NULL, self, 32768);
    if (units == 0 || units + 32 >= 32768) return 30;
    swprintf(invocation, 32768, L"\"%ls\" commit-then-exit", self);
    STARTUPINFOW startup;
    PROCESS_INFORMATION child;
    memset(&startup, 0, sizeof(startup)); startup.cb = sizeof(startup);
    memset(&child, 0, sizeof(child));
    if (!CreateProcessW(self, invocation, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &startup, &child)) return 31;
    CloseHandle(child.hThread);
    DWORD code = 0;
    if (WaitForSingleObject(child.hProcess, 15000) != WAIT_OBJECT_0 || !GetExitCodeProcess(child.hProcess, &code)) {
        TerminateProcess(child.hProcess, 1); CloseHandle(child.hProcess); return 32;
    }
    CloseHandle(child.hProcess);
    if (code != 73) { fprintf(stderr, "fault child exit=%lu\n", (unsigned long)code); return 33; }
    wchar_t temporary[1024], directory[1200], control[1300], log[1300];
    if (!GetTempPathW(1024, temporary)) return 34;
    swprintf(directory, 1200, L"%lsbtrc-transfer-api-%lu", temporary, (unsigned long)child.dwProcessId);
    swprintf(control, 1300, L"%ls\\worker.control", directory);
    swprintf(log, 1300, L"%ls\\worker.log", directory);
    uint64_t deadline = GetTickCount64() + 5000;
    const char *prefix = "btrc-daemon-v1\na3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3\n";
    unsigned long pid = 0;
    do {
        HANDLE record = CreateFileW(control, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (record != INVALID_HANDLE_VALUE) {
            char bytes[80] = { 0 }; DWORD read = 0;
            BOOL received = ReadFile(record, bytes, sizeof(bytes) - 1, &read, NULL);
            CloseHandle(record);
            if (received && read > strlen(prefix) && strncmp(bytes, prefix, strlen(prefix)) == 0) {
                char *end = NULL;
                pid = strtoul(bytes + strlen(prefix), &end, 10);
                if (pid >= 2 && pid <= INT_MAX && end != NULL && strcmp(end, "\n") == 0) break;
                pid = 0;
            }
        }
        Sleep(1);
    } while (GetTickCount64() < deadline);
    if (pid == 0) return 35;
    HANDLE observer = OpenProcess(SYNCHRONIZE | PROCESS_TERMINATE, FALSE, (DWORD)pid);
    if (observer == NULL || WaitForSingleObject(observer, 100) != WAIT_TIMEOUT) return 38;
    if (!TerminateProcess(observer, 0) || WaitForSingleObject(observer, 5000) != WAIT_OBJECT_0
            || !CloseHandle(observer)) return 39;
    if (!DeleteFileW(control) || !DeleteFileW(log) || !RemoveDirectoryW(directory)) return 40;
    return 0;
}
#endif

int main(int argc, char **argv) {
#if defined(BTRC_DAEMON_FAULT_FIXTURE)
    if (argc != 2) return 41;
    if (strcmp(argv[1], "commit-exit-parent") == 0) {
        int status = commit_exit_parent();
        if (status != 0) fprintf(stderr, "commit-exit-parent failure=%d\n", status);
        else puts("daemon-transfer-fault PASS");
        return status;
    }
    uint32_t expected = strcmp(argv[1], "kill-before-commit") == 0 ? 1 : 2;
    int live = strcmp(argv[1], "drop-ack") == 0;
    int status = transfer_case(strcmp(argv[1], "commit-then-exit") == 0 ? "commit-35" : "commit-34", expected, live);
    if (status != 0) fprintf(stderr, "fault=%s failure=%d\n", argv[1], status);
    else puts("daemon-transfer-fault PASS");
    return status;
#else
    (void)argc; (void)argv;
    const char *names[] = { "commit-34", "prepare/bad", "commit-25", "commit-26" };
    const uint32_t expected[] = { 0, 1, 2, 2 };
    for (size_t index = 0; index < sizeof(names) / sizeof(names[0]); index++) {
        int status = transfer_case(names[index], expected[index], expected[index] == 0);
        if (status != 0) { fprintf(stderr, "case=%s failure=%d\n", names[index], status); return status; }
    }
    puts("daemon-transfer PASS");
    return 0;
#endif
}
