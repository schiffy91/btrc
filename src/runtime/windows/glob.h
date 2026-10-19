/* POSIX <glob.h> for the MinGW-w64 Windows rows, which ship none.

   glob is musl 1.2.5's directory walk (musl/glob.c, MIT; see musl/COPYRIGHT)
   with a UTF-16 directory reader: names come from UCRT's _wfindfirst64 and
   _wfindnext64 (FindFirstFileExW) and are matched and returned as UTF-8, so
   non-ASCII paths work outside the active code page. btrc_win_musl.h compiles
   it into the including translation unit with internal linkage, as regex.h
   does the regex engine.

   As on POSIX, '/' separates components and a backslash escapes the next
   character unless GLOB_NOESCAPE is given; a pattern may start with a drive
   ("C:/...") or a UNC share. Results are sorted bytewise, as in the C locale.
   The GNU extensions GLOB_PERIOD and GLOB_TILDE are not provided. */
#pragma once

#include <stddef.h>

#include "fnmatch.h"

typedef struct {
	size_t gl_pathc;
	char **gl_pathv;
	size_t gl_offs;
	int __dummy1;
	void *__dummy2[5];
} glob_t;

#define GLOB_ERR      0x01
#define GLOB_MARK     0x02
#define GLOB_NOSORT   0x04
#define GLOB_DOOFFS   0x08
#define GLOB_NOCHECK  0x10
#define GLOB_APPEND   0x20
#define GLOB_NOESCAPE 0x40

#define GLOB_NOSPACE 1
#define GLOB_ABORTED 2
#define GLOB_NOMATCH 3

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
static int btrc_win_glob(const char *restrict, int, int (*)(const char *, int), glob_t *restrict);
static void btrc_win_globfree(glob_t *);
#pragma GCC diagnostic pop

#define glob btrc_win_glob
#define globfree btrc_win_globfree

#define BTRC_WIN_MUSL_PART_GLOB
#include "btrc_win_musl.h"
#undef BTRC_WIN_MUSL_PART_GLOB
