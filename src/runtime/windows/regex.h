/* POSIX <regex.h> for the MinGW-w64 Windows rows (windows-x86_64,
   windows-aarch64). MinGW-w64 ships no regular-expression engine (PLAN.md
   D22: "Windows regex: a vendored POSIX regex").

   The engine is musl 1.2.5's TRE-derived regcomp/regexec (musl/, MIT and
   BSD-2-Clause; see musl/COPYRIGHT and README.md). This header declares the
   POSIX interface and compiles the engine into the including translation
   unit with internal linkage, so every build that already puts this overlay
   on its include path (Makefile WIN_COMPAT, tools/native_plan.py, the target
   runner, windows.yml) links it without a separate object, and several units
   of one program each keep a private copy. btrc_win_musl.h gives the engine's
   own file-scope names a btrc_win_musl_ prefix and restores every macro it
   touches, so the names below are the only ones this header adds.

   Matching follows the C locale every btrc program runs in, as glibc and
   macOS do there: each byte is one character, and character classes and
   REG_ICASE cover ASCII only. */
#pragma once

#include <stddef.h>

typedef ptrdiff_t regoff_t;

typedef struct re_pattern_buffer {
	size_t re_nsub;
	void *__opaque, *__padding[4];
	size_t __nsub2;
	char __padding2;
} regex_t;

typedef struct {
	regoff_t rm_so;
	regoff_t rm_eo;
} regmatch_t;

#define REG_EXTENDED    1
#define REG_ICASE       2
#define REG_NEWLINE     4
#define REG_NOSUB       8

#define REG_NOTBOL      1
#define REG_NOTEOL      2

#define REG_OK          0
#define REG_NOMATCH     1
#define REG_BADPAT      2
#define REG_ECOLLATE    3
#define REG_ECTYPE      4
#define REG_EESCAPE     5
#define REG_ESUBREG     6
#define REG_EBRACK      7
#define REG_EPAREN      8
#define REG_EBRACE      9
#define REG_BADBR       10
#define REG_ERANGE      11
#define REG_ESPACE      12
#define REG_BADRPT      13

#define REG_ENOSYS      -1

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
static int btrc_win_regcomp(regex_t *restrict, const char *restrict, int);
static int btrc_win_regexec(const regex_t *restrict, const char *restrict, size_t, regmatch_t *restrict, int);
static void btrc_win_regfree(regex_t *);
static size_t btrc_win_regerror(int, const regex_t *restrict, char *restrict, size_t);
#pragma GCC diagnostic pop

#define regcomp btrc_win_regcomp
#define regexec btrc_win_regexec
#define regfree btrc_win_regfree
#define regerror btrc_win_regerror

#define BTRC_WIN_MUSL_PART_REGEX
#include "btrc_win_musl.h"
#undef BTRC_WIN_MUSL_PART_REGEX
