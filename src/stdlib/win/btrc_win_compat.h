/* btrc Windows compatibility layer (force-included via `-include` on Windows
   builds only; POSIX builds never see this file).

   The missing-FILE shims (regex.h, sys/wait.h, …) live beside this header and
   are found via `-I`. This header handles missing-SYMBOL gaps: POSIX functions
   MinGW-w64 omits but that the emitted C still references.

   Implemented adapters have the documented Windows semantics below; some
   compatibility probes intentionally return sentinels or fail closed. Features
   that need a real Win32 backend to behave correctly (Process spawn/wait,
   raw-mode Terminal, sockets, Regex, glob/fnmatch) are deliberately left out:
   stubbing those operations would link but misbehave. */
#pragma once
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <io.h>      /* _mktemp_s */
#include <direct.h>  /* _mkdir   */

#include "btrc_win_errors.h"

/* MinGW exposes popen/pclose as object-like macros naming imported UCRT
   symbols. A later portable `extern popen(...)` declaration then loses the
   dllimport attribute under macro expansion and fails strict Clang builds.
   Route both operations through internal wrappers before generated extern
   declarations are parsed; a following extern declaration inherits the
   wrappers' already-established internal linkage. */
static inline FILE* btrc_win_popen(const char* command, const char* mode) {
    return _popen(command, mode);
}
static inline int btrc_win_pclose(FILE* stream) {
    return _pclose(stream);
}
#ifdef popen
#undef popen
#endif
#define popen btrc_win_popen
#ifdef pclose
#undef pclose
#endif
#define pclose btrc_win_pclose

/* Keep the forced-include boundary narrow: importing windows.h here would
   inject thousands of unrelated typedefs and macros into every generated
   translation unit.  These are the exact Win32 filesystem seams used below.
   x86_64 Windows uses the platform's single C calling convention, and MinGW's
   default system libraries provide both symbols without dllimport syntax. */
#ifndef BTRC_WIN_GET_FILE_ATTRIBUTES
#define BTRC_WIN_GET_FILE_ATTRIBUTES GetFileAttributesA
#endif
#ifndef BTRC_WIN_REMOVE_DIRECTORY
#define BTRC_WIN_REMOVE_DIRECTORY RemoveDirectoryA
#endif
unsigned long BTRC_WIN_GET_FILE_ATTRIBUTES(const char *path);
int BTRC_WIN_REMOVE_DIRECTORY(const char *path);

#ifndef INVALID_FILE_ATTRIBUTES
#define INVALID_FILE_ATTRIBUTES ((unsigned long)-1)
#endif
#ifndef FILE_ATTRIBUTE_DIRECTORY
#define FILE_ATTRIBUTE_DIRECTORY 0x00000010UL
#endif
#ifndef FILE_ATTRIBUTE_REPARSE_POINT
#define FILE_ATTRIBUTE_REPARSE_POINT 0x00000400UL
#endif

/* Process launch has no Windows backend yet and must fail before fork/spawn.
   Map the POSIX environ symbol to a null, translation-unit-local sentinel so
   imported process code still cross-compiles without colliding with UCRT's
   function-like `_environ` macro. */
#ifdef environ
#undef environ
#endif
static char **btrc_windows_process_environment = NULL;
#define environ btrc_windows_process_environment

/* Treat every final-component reparse point (including directory junctions) as
   a link. The stdlib can then unlink that name without enumerating its target.
   These narrow Win32 APIs follow the active Windows code-page contract. */
#ifndef S_IFLNK
#define S_IFLNK 0120000
#endif
#ifndef S_IFMT
#define S_IFMT _S_IFMT
#endif
#ifndef S_ISLNK
#define S_ISLNK(m) (((m) & S_IFMT) == S_IFLNK)
#endif
static inline int btrc_lstat(const char *path, struct stat *status) {
    (void)btrc_windows_process_environment;
    if (!path || !status) { errno = EINVAL; return -1; }
    unsigned long attributes = BTRC_WIN_GET_FILE_ATTRIBUTES(path);
    if (attributes == INVALID_FILE_ATTRIBUTES) {
        btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
        return -1;
    }
    if ((attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        memset(status, 0, sizeof(*status));
        status->st_mode = S_IFLNK;
        return 0;
    }
    return stat(path, status);
}
#ifdef lstat
#undef lstat
#endif
#define lstat(path, status) btrc_lstat((path), (status))

/* _unlink cannot remove a directory junction; RemoveDirectory removes the
   reparse point itself and never traverses its target. */
static inline int btrc_unlink(const char *path) {
    if (!path) { errno = EINVAL; return -1; }
    unsigned long attributes = BTRC_WIN_GET_FILE_ATTRIBUTES(path);
    if (attributes == INVALID_FILE_ATTRIBUTES) {
        btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
        return -1;
    }
    if ((attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0
            && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
        if (BTRC_WIN_REMOVE_DIRECTORY(path)) { return 0; }
        btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
        return -1;
    }
    return _unlink(path);
}
#ifdef unlink
#undef unlink
#endif
#define unlink(path) btrc_unlink(path)

/* Ordinary directory recursion is unsupported on Windows until the stdlib has
   a handle-relative NT backend. POSIX descriptor primitives fail closed if
   their functions are retained in the same translation unit. */
#ifndef AT_SYMLINK_NOFOLLOW
#define AT_SYMLINK_NOFOLLOW 0x100
#endif
#ifndef AT_REMOVEDIR
#define AT_REMOVEDIR 0x200
#endif
/* UCRT can make ordinary descriptors non-inheritable, but it has no `_open`
   equivalent for POSIX final-component no-follow or directory-only opens.
   Preserve those intentions as private flag bits and reject them at the open
   seam rather than silently following a junction or accepting a regular file. */
#ifdef O_CLOEXEC
#undef O_CLOEXEC
#endif
#define O_CLOEXEC _O_NOINHERIT
#ifdef O_DIRECTORY
#undef O_DIRECTORY
#endif
#define O_DIRECTORY 0x10000000
#ifdef O_NOFOLLOW
#undef O_NOFOLLOW
#endif
#define O_NOFOLLOW 0x20000000
#ifndef O_NONBLOCK
#define O_NONBLOCK 0
#endif

static inline int btrc_open(const char *path, int flags, ...) {
    if (!path) { errno = EINVAL; return -1; }
    if ((flags & (O_DIRECTORY | O_NOFOLLOW)) != 0) {
        errno = ENOTSUP;
        return -1;
    }
    if ((flags & O_CREAT) != 0) {
        va_list arguments;
        va_start(arguments, flags);
        int mode = va_arg(arguments, int);
        va_end(arguments);
        return _open(path, flags, mode);
    }
    return _open(path, flags);
}
#ifdef open
#undef open
#endif
#define open(...) btrc_open(__VA_ARGS__)

/* Descriptor-relative permission hardening has no faithful UCRT equivalent.
   Exact private-directory capabilities reject Windows before reaching this
   seam, so retained POSIX bodies must fail closed rather than silently omit
   their permission check. */
static inline int btrc_fchmod(int descriptor, mode_t mode) {
    (void)descriptor; (void)mode;
    errno = ENOTSUP;
    return -1;
}
#ifdef fchmod
#undef fchmod
#endif
#define fchmod(descriptor, mode) btrc_fchmod((descriptor), (mode))

static inline int btrc_openat(int directory, const char *path, int flags, ...) {
    (void)directory; (void)path; (void)flags;
    errno = ENOTSUP;
    return -1;
}
static inline int btrc_fstatat(int directory, const char *path,
                              struct stat *status, int flags) {
    (void)directory; (void)path; (void)status; (void)flags;
    errno = ENOTSUP;
    return -1;
}
static inline int btrc_unlinkat(int directory, const char *path, int flags) {
    (void)directory; (void)path; (void)flags;
    errno = ENOTSUP;
    return -1;
}
static inline int btrc_mkdirat(
        int directory, const char *path, mode_t mode) {
    (void)directory; (void)path; (void)mode;
    errno = ENOTSUP;
    return -1;
}
static inline int btrc_renameat(
        int old_directory, const char *old_path,
        int new_directory, const char *new_path) {
    (void)old_directory; (void)old_path;
    (void)new_directory; (void)new_path;
    errno = ENOTSUP;
    return -1;
}
#define openat(...) btrc_openat(__VA_ARGS__)
#define fstatat(directory, path, status, flags) \
    btrc_fstatat((directory), (path), (status), (flags))
#define unlinkat(directory, path, flags) \
    btrc_unlinkat((directory), (path), (flags))
#define mkdirat(directory, path, mode) \
    btrc_mkdirat((directory), (path), (mode))
#define renameat(old_directory, old_path, new_directory, new_path) \
    btrc_renameat((old_directory), (old_path), \
        (new_directory), (new_path))
#define fdopendir(descriptor) ((void)(descriptor), (DIR *)0)
#define dirfd(directory) ((void)(directory), -1)

/* No POSIX uid/gid model on Windows; report the "privileged" sentinel 0. */
#ifndef geteuid
#define geteuid() (0)
#endif
#ifndef getuid
#define getuid() (0)
#endif

/* Thread-safe time conversions: copy out of the (thread-local on UCRT) buffer.
   Plain gmtime/localtime are always available, unlike gmtime_s/localtime_s. */
static inline struct tm *btrc_gmtime_r(const time_t *t, struct tm *out) {
    struct tm *r = gmtime(t);
    if (r) { *out = *r; return out; }
    return (struct tm *)0;
}
static inline struct tm *btrc_localtime_r(const time_t *t, struct tm *out) {
    struct tm *r = localtime(t);
    if (r) { *out = *r; return out; }
    return (struct tm *)0;
}
#ifndef gmtime_r
#define gmtime_r(t, out) btrc_gmtime_r((t), (out))
#endif
#ifndef localtime_r
#define localtime_r(t, out) btrc_localtime_r((t), (out))
#endif

/* Environment variables: real Windows behaviour via _putenv_s. */
static inline int btrc_setenv(const char *name, const char *value, int overwrite) {
    if (!name || !name[0] || strchr(name, '=')) { errno = EINVAL; return -1; }
    if (!overwrite && getenv(name) != NULL) { return 0; }
    int error = _putenv_s(name, value ? value : "");
    if (error != 0) { errno = error; return -1; }
    return 0;
}
static inline int btrc_unsetenv(const char *name) {
    if (!name || !name[0] || strchr(name, '=')) { errno = EINVAL; return -1; }
    int error = _putenv_s(name, "");
    if (error != 0) { errno = error; return -1; }
    return 0;
}
#ifndef setenv
#define setenv(n, v, o) btrc_setenv((n), (v), (o))
#endif
#ifndef unsetenv
#define unsetenv(n) btrc_unsetenv((n))
#endif

/* POSIX mkdir(path, mode) -> Windows _mkdir(path): Windows has no POSIX mode
   bits, so the mode expression is evaluated and then ignored. MinGW already
   aliases a 1-arg mkdir, so undef first. */
#ifdef mkdir
#undef mkdir
#endif
#define mkdir(path, mode) ((void)(mode), _mkdir(path))

/* realpath: resolve the final reparse target through a dynamically sized,
   UTF-16 Win32 path. Only the allocation form (resolved_path == NULL) is
   supported, so callers never expose an unbounded destination buffer. */
#include "btrc_win_realpath.h"
#ifndef realpath
#define realpath(p, r) btrc_realpath((p), (r))
#endif

/* mkdtemp: create a uniquely-named temp directory. Keep the implementation
   inline because this header is force-included into every translation unit;
   a header-level external definition would fail when native shims are linked. */
static inline char *mkdtemp(char *tmpl) {
    if (!tmpl) { errno = EINVAL; return (char *)0; }
    size_t length = strlen(tmpl);
    if (length < 6 || length == SIZE_MAX ||
        memcmp(tmpl + length - 6, "XXXXXX", 6) != 0) {
        errno = EINVAL;
        return (char *)0;
    }
    size_t size = length + 1;
    char *original = (char *)malloc(size);
    if (!original) { errno = ENOMEM; return (char *)0; }
    memcpy(original, tmpl, size);
    for (int attempt = 0; attempt < 128; attempt++) {
        memcpy(tmpl, original, size);
        int error = _mktemp_s(tmpl, size);
        if (error != 0) {
            free(original);
            errno = error;
            return (char *)0;
        }
        if (_mkdir(tmpl) == 0) {
            free(original);
            return tmpl;
        }
        if (errno != EEXIST) {
            int mkdir_error = errno;
            free(original);
            errno = mkdir_error;
            return (char *)0;
        }
    }
    free(original);
    errno = EEXIST;
    return (char *)0;
}
