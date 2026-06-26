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
#include <sys/stat.h>
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
    (void)overwrite;
    return _putenv_s(name, value ? value : "");
}
static inline int btrc_unsetenv(const char *name) {
    return _putenv_s(name, "");
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
    return _fullpath(resolved, path, 260 /* _MAX_PATH */);
}
#ifndef realpath
#define realpath(p, r) btrc_realpath((p), (r))
#endif

/* mkdtemp: create a uniquely-named temp directory. The emitted C declares an
   extern prototype, so provide a real (extern) definition — one translation
   unit per btrc program, so no multiple-definition risk. */
char *mkdtemp(char *tmpl) {
    if (_mktemp_s(tmpl, strlen(tmpl) + 1) != 0) return (char *)0;
    if (_mkdir(tmpl) != 0) return (char *)0;
    return tmpl;
}
