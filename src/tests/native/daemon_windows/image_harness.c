/* Native verification and held-image ownership, without launching a child. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>
#include "windows_os.h"
#include "windows_daemon_image.h"

#if defined(_WIN32)
#include <windows.h>

int main(int argc, char **argv) {
    int expect_failure = argc == 3 && strcmp(argv[1], "--refuse") == 0;
    uint32_t expected_code = expect_failure ? (uint32_t)strtoul(argv[2], NULL, 10) : 0;
    __btrc_windows_launch_error_t error;
    __btrc_windows_image_owner *image = NULL;
    int status = __btrc_windows_supervisor_image_verify(&image, &error);
    if (expect_failure) {
        if (status == 0 || image != NULL || error.stage == 0 || error.ownership_state != 0
                || (expected_code != 0 && error.native_code != expected_code)) {
            fprintf(stderr, "refusal status=%d owner=%d stage=%u domain=%u code=%u ownership=%u\n",
                status, image != NULL, (unsigned)error.stage, (unsigned)error.domain,
                (unsigned)error.native_code, (unsigned)error.ownership_state);
            return 1;
        }
        DWORD before = 0, after = 0;
        if (!GetProcessHandleCount(GetCurrentProcess(), &before)) return 16;
        for (int iteration = 0; iteration < 8; iteration++) {
            if (__btrc_windows_supervisor_image_verify(&image, &error) == 0 || image != NULL
                    || error.stage == 0 || error.ownership_state != 0
                    || (expected_code != 0 && error.native_code != expected_code)) return 17;
        }
        if (!GetProcessHandleCount(GetCurrentProcess(), &after) || before != after) return 18;
        puts("image-refusal PASS");
        return 0;
    }
    if (status != 0 || image == NULL) {
        fprintf(stderr, "verify stage=%u domain=%u code=%u ownership=%u\n", (unsigned)error.stage,
            (unsigned)error.domain, (unsigned)error.native_code, (unsigned)error.ownership_state);
        return 2;
    }
    if (__btrc_windows_supervisor_image_close(&image, &error) != 0 || image != NULL) return 3;
    DWORD before = 0, after = 0;
    if (!GetProcessHandleCount(GetCurrentProcess(), &before)) return 4;
    for (int iteration = 0; iteration < 8; iteration++) {
        if (__btrc_windows_supervisor_image_verify(&image, &error) != 0 || image == NULL) return 5;
        wchar_t module[32768];
        DWORD count = GetModuleFileNameW(NULL, module, 32768);
        if (count == 0 || count >= 32768) return 6;
        wchar_t *leaf = wcsrchr(module, L'\\');
        if (leaf == NULL) return 7;
        size_t available = 32768u - (size_t)(leaf + 1 - module);
        if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                __btrc_windows_daemon_metadata.basename_utf8, -1, leaf + 1, (int)available) == 0) return 8;
        HANDLE writer = CreateFileW(module, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (writer != INVALID_HANDLE_VALUE) { CloseHandle(writer); return 9; }
        if (GetLastError() != ERROR_SHARING_VIOLATION || DeleteFileW(module)) return 10;
        /* The directory hold prevents rename but must not forbid new entries. */
        if (available < sizeof(L"ImageHoldUnrelated.tmp") / sizeof(wchar_t)) return 19;
        wcscpy(leaf + 1, L"ImageHoldUnrelated.tmp");
        HANDLE unrelated = CreateFileW(module, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
        if (unrelated == INVALID_HANDLE_VALUE) return 11;
        if (!CloseHandle(unrelated) || !DeleteFileW(module)) return 12;
        if (__btrc_windows_supervisor_image_close(&image, &error) != 0 || image != NULL) return 13;
        if (__btrc_windows_supervisor_image_close(&image, &error) != 0) return 14;
    }
    if (!GetProcessHandleCount(GetCurrentProcess(), &after) || before != after) {
        fprintf(stderr, "handle census %lu -> %lu\n", (unsigned long)before, (unsigned long)after);
        return 15;
    }
    puts("image-verification PASS");
    return 0;
}
#else
int main(void) {
    __btrc_windows_launch_error_t error;
    __btrc_windows_image_owner *image = (__btrc_windows_image_owner *)(void *)&error;
    if (__btrc_windows_supervisor_image_verify(&image, &error) == 0 || image != NULL
            || error.stage != 15 || error.domain != 4 || error.ownership_state != 0) return 1;
    if (__btrc_windows_supervisor_image_close(&image, &error) != 0) return 2;
    __btrc_windows_transfer_result result = { 99, 99, 99 };
    if (__btrc_windows_supervisor_transfer(NULL, NULL, NULL, 0, &result, &error) == 0
            || result.state != 1 || result.supervisor_pid != 0 || result.lifetime != 0
            || error.stage != 15 || error.domain != 4 || error.ownership_state != 0) return 3;
    puts("image-unsupported PASS");
    return 0;
}
#endif
