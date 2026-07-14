/* btrc Windows compatibility layer (force-included via `-include` on Windows
   builds only; POSIX builds never see this file).

   The missing-FILE shims (regex.h, sys/wait.h, …) live beside this header and
   are found via `-I`. This header handles missing-SYMBOL gaps: POSIX functions
   MinGW-w64 omits but that the emitted C still references.

   Everything here is a *correct* Windows equivalent — not a stub that merely
   links. Features that need a real Win32 backend to behave correctly (Process
   spawn/wait, raw-mode Terminal, sockets, Regex, glob/fnmatch) are deliberately
   left out: those are Milestone 2, and stubbing them would link but misbehave. */
#pragma once
#include <errno.h>
#include <sys/stat.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <io.h>      /* _mktemp_s */
#include <direct.h>  /* _mkdir   */

/* Windows has no POSIX symlinks. */
#ifndef lstat
#define lstat stat
#endif
#ifndef S_ISLNK
#define S_ISLNK(m) (0)
#endif

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
   bits, so the mode is dropped. MinGW already aliases a 1-arg mkdir, so undef
   first. (My mkdtemp above calls _mkdir directly and is unaffected.) */
#ifdef mkdir
#undef mkdir
#endif
#define mkdir(path, mode) _mkdir(path)

/* realpath: canonicalise a path. Windows' _fullpath is the direct equivalent
   (allocates when the output buffer is NULL, like POSIX realpath). */
static inline char *btrc_realpath(const char *path, char *resolved) {
    if (!path) { errno = EINVAL; return (char *)0; }
    return _fullpath(resolved, path, _MAX_PATH);
}
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
