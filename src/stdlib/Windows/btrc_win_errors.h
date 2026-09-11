/* Shared Win32 error-to-errno translation for the narrow compatibility seams. */
#pragma once

#include <errno.h>

/* The indirection is a native-test seam. Production builds use GetLastError;
   focused tests replace it without importing windows.h into generated code. */
#ifndef BTRC_WIN_GET_LAST_ERROR
#define BTRC_WIN_GET_LAST_ERROR GetLastError
#endif
unsigned long BTRC_WIN_GET_LAST_ERROR(void);

static inline void btrc_win_path_error(unsigned long error) {
    switch (error) {
        case 2UL:   /* ERROR_FILE_NOT_FOUND */
        case 3UL:   /* ERROR_PATH_NOT_FOUND */
            errno = ENOENT;
            break;
        case 5UL:   /* ERROR_ACCESS_DENIED */
        case 32UL:  /* ERROR_SHARING_VIOLATION */
            errno = EACCES;
            break;
        case 8UL:   /* ERROR_NOT_ENOUGH_MEMORY */
        case 14UL:  /* ERROR_OUTOFMEMORY */
            errno = ENOMEM;
            break;
        case 15UL:  /* ERROR_INVALID_DRIVE */
            errno = ENODEV;
            break;
        case 21UL:  /* ERROR_NOT_READY */
            errno = EBUSY;
            break;
        case 50UL:  /* ERROR_NOT_SUPPORTED */
            errno = ENOTSUP;
            break;
        case 80UL:  /* ERROR_FILE_EXISTS */
        case 183UL: /* ERROR_ALREADY_EXISTS */
            errno = EEXIST;
            break;
        case 87UL:  /* ERROR_INVALID_PARAMETER */
        case 123UL: /* ERROR_INVALID_NAME */
        case 161UL: /* ERROR_BAD_PATHNAME */
            errno = EINVAL;
            break;
        case 145UL: /* ERROR_DIR_NOT_EMPTY */
            errno = ENOTEMPTY;
            break;
        case 206UL: /* ERROR_FILENAME_EXCED_RANGE */
            errno = ENAMETOOLONG;
            break;
        case 267UL: /* ERROR_DIRECTORY */
            errno = ENOTDIR;
            break;
        case 1113UL: /* ERROR_NO_UNICODE_TRANSLATION */
            errno = EILSEQ;
            break;
        default:
            errno = EIO;
            break;
    }
}
