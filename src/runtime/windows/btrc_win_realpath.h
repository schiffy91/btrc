/* Dynamic, reparse-aware Windows implementation of POSIX realpath. */
#pragma once

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "btrc_win_errors.h"

/* Keep windows.h out of generated translation units. These declarations use
   the exact Win32 ABI types needed by this seam; the supported target is
   x86_64-windows-gnu, where system functions use the platform convention. */
struct _SECURITY_ATTRIBUTES;
void *CreateFileW(const wchar_t *name, unsigned long access,
                  unsigned long sharing, struct _SECURITY_ATTRIBUTES *security,
                  unsigned long creation, unsigned long flags,
                  void *template_file);
unsigned long GetFinalPathNameByHandleW(void *file, wchar_t *path,
                                        unsigned long capacity,
                                        unsigned long flags);
int CloseHandle(void *object);
int MultiByteToWideChar(unsigned int code_page, unsigned long flags,
                        const char *input, int input_length,
                        wchar_t *output, int output_length);
int WideCharToMultiByte(unsigned int code_page, unsigned long flags,
                        const wchar_t *input, int input_length,
                        char *output, int output_length,
                        const char *default_character,
                        int *used_default_character);

#define BTRC_WIN_INVALID_HANDLE ((void *)(intptr_t)-1)
#define BTRC_WIN_FILE_READ_ATTRIBUTES 0x00000080UL
#define BTRC_WIN_FILE_SHARE_ALL 0x00000007UL
#define BTRC_WIN_OPEN_EXISTING 3UL
#define BTRC_WIN_FILE_FLAG_BACKUP_SEMANTICS 0x02000000UL
#define BTRC_WIN_CP_UTF8 65001U
#define BTRC_WIN_MB_ERR_INVALID_CHARS 0x00000008UL
#define BTRC_WIN_WC_ERR_INVALID_CHARS 0x00000080UL

static inline wchar_t *btrc_win_path_to_wide(const char *path) {
    int length = MultiByteToWideChar(BTRC_WIN_CP_UTF8,
        BTRC_WIN_MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (length <= 0 || (size_t)length > SIZE_MAX / sizeof(wchar_t)) {
        btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
        return NULL;
    }
    wchar_t *wide = (wchar_t *)malloc((size_t)length * sizeof(wchar_t));
    if (!wide) { errno = ENOMEM; return NULL; }
    if (MultiByteToWideChar(BTRC_WIN_CP_UTF8,
            BTRC_WIN_MB_ERR_INVALID_CHARS, path, -1, wide, length) != length) {
        unsigned long error = BTRC_WIN_GET_LAST_ERROR();
        free(wide);
        btrc_win_path_error(error);
        return NULL;
    }
    return wide;
}

static inline wchar_t *btrc_win_final_path(void *file) {
    unsigned long capacity = 256UL;
    wchar_t *wide = NULL;
    for (;;) {
        if ((size_t)capacity > SIZE_MAX / sizeof(wchar_t)) {
            free(wide);
            errno = ENAMETOOLONG;
            return NULL;
        }
        wchar_t *grown = (wchar_t *)realloc(
            wide, (size_t)capacity * sizeof(wchar_t));
        if (!grown) { free(wide); errno = ENOMEM; return NULL; }
        wide = grown;
        unsigned long length = GetFinalPathNameByHandleW(
            file, wide, capacity, 0UL);
        if (length == 0UL) {
            unsigned long error = BTRC_WIN_GET_LAST_ERROR();
            free(wide);
            btrc_win_path_error(error);
            return NULL;
        }
        if (length < capacity) { return wide; }
        if (length == UINT32_MAX) {
            free(wide);
            errno = ENAMETOOLONG;
            return NULL;
        }
        capacity = length + 1UL;
    }
}

static inline void btrc_win_strip_extended_prefix(wchar_t *path) {
    size_t length = wcslen(path);
    if (length < 4 || path[0] != L'\\' || path[1] != L'\\'
            || path[2] != L'?' || path[3] != L'\\') {
        return;
    }
    if (length >= 8 && path[4] == L'U' && path[5] == L'N'
            && path[6] == L'C' && path[7] == L'\\') {
        path[0] = L'\\';
        path[1] = L'\\';
        memmove(path + 2, path + 8,
                (length - 8 + 1) * sizeof(wchar_t));
        return;
    }
    if (length >= 6 && path[5] == L':'
            && ((path[4] >= L'A' && path[4] <= L'Z')
                || (path[4] >= L'a' && path[4] <= L'z'))) {
        memmove(path, path + 4, (length - 4 + 1) * sizeof(wchar_t));
    }
}

static inline char *btrc_win_path_to_utf8(const wchar_t *wide) {
    int length = WideCharToMultiByte(BTRC_WIN_CP_UTF8,
        BTRC_WIN_WC_ERR_INVALID_CHARS, wide, -1, NULL, 0, NULL, NULL);
    if (length <= 0) {
        btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
        return NULL;
    }
    char *path = (char *)malloc((size_t)length);
    if (!path) { errno = ENOMEM; return NULL; }
    if (WideCharToMultiByte(BTRC_WIN_CP_UTF8,
            BTRC_WIN_WC_ERR_INVALID_CHARS, wide, -1, path, length,
            NULL, NULL) != length) {
        unsigned long error = BTRC_WIN_GET_LAST_ERROR();
        free(path);
        btrc_win_path_error(error);
        return NULL;
    }
    return path;
}

static inline char *btrc_realpath(const char *path, char *resolved) {
    /* POSIX realpath cannot know the capacity of a caller-provided buffer.
       Windows paths can exceed PATH_MAX, so this compatibility API only accepts
       the allocation form realpath(path, NULL). */
    if (!path || resolved) { errno = EINVAL; return NULL; }
    wchar_t *wide_input = btrc_win_path_to_wide(path);
    if (!wide_input) { return NULL; }
    void *file = CreateFileW(wide_input, BTRC_WIN_FILE_READ_ATTRIBUTES,
        BTRC_WIN_FILE_SHARE_ALL, NULL, BTRC_WIN_OPEN_EXISTING,
        BTRC_WIN_FILE_FLAG_BACKUP_SEMANTICS, NULL);
    unsigned long create_error = file == BTRC_WIN_INVALID_HANDLE
        ? BTRC_WIN_GET_LAST_ERROR() : 0UL;
    free(wide_input);
    if (file == BTRC_WIN_INVALID_HANDLE) {
        btrc_win_path_error(create_error);
        return NULL;
    }
    wchar_t *wide_final = btrc_win_final_path(file);
    int close_ok = CloseHandle(file);
    if (!wide_final) { return NULL; }
    if (!close_ok) {
        unsigned long error = BTRC_WIN_GET_LAST_ERROR();
        free(wide_final);
        btrc_win_path_error(error);
        return NULL;
    }
    btrc_win_strip_extended_prefix(wide_final);
    char *allocated = btrc_win_path_to_utf8(wide_final);
    free(wide_final);
    return allocated;
}
