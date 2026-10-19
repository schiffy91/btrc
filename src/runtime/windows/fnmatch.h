/* POSIX <fnmatch.h> for the MinGW-w64 Windows rows, which ship none.

   fnmatch is musl 1.2.5's matcher (musl/fnmatch.c, MIT; see musl/COPYRIGHT),
   compiled into the including translation unit with internal linkage by
   btrc_win_musl.h exactly as regex.h compiles the regex engine. Like regex.h
   it matches bytes with the C locale's ASCII classes, as glibc and macOS do
   in the C locale every btrc program runs in. */
#pragma once

#define FNM_PATHNAME    0x1
#define FNM_NOESCAPE    0x2
#define FNM_PERIOD      0x4
#define FNM_LEADING_DIR 0x8
#define FNM_CASEFOLD    0x10
#define FNM_FILE_NAME   FNM_PATHNAME

#define FNM_NOMATCH 1
#define FNM_NOSYS   (-1)

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
static int btrc_win_fnmatch(const char *, const char *, int);
#pragma GCC diagnostic pop

#define fnmatch btrc_win_fnmatch

#define BTRC_WIN_MUSL_PART_FNMATCH
#include "btrc_win_musl.h"
#undef BTRC_WIN_MUSL_PART_FNMATCH
