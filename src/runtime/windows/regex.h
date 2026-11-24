/* POSIX <regex.h> for the MinGW-w64 Windows rows (windows-x86_64,
   windows-aarch64). MinGW-w64 ships no regular-expression engine (PLAN.md
   D22: "Windows regex: a vendored POSIX regex").

   Single-atom and literal EREs use first-party byte matchers. Other patterns and flags
   use musl 1.2.5's TRE-derived regcomp/regexec (musl/, MIT and BSD-2-Clause;
   see musl/COPYRIGHT and README.md). This header declares the
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
static int btrc_win_legacy_regcomp(regex_t *restrict, const char *restrict, int);
static int btrc_win_legacy_regexec(const regex_t *restrict, const char *restrict, size_t, regmatch_t *restrict, int);
static void btrc_win_legacy_regfree(regex_t *);
static size_t btrc_win_legacy_regerror(int, const regex_t *restrict, char *restrict, size_t);
#pragma GCC diagnostic pop

#define regcomp btrc_win_legacy_regcomp
#define regexec btrc_win_legacy_regexec
#define regfree btrc_win_legacy_regfree
#define regerror btrc_win_legacy_regerror

#define BTRC_WIN_MUSL_PART_REGEX
#include "btrc_win_musl.h"
#undef BTRC_WIN_MUSL_PART_REGEX

#undef regcomp
#undef regexec
#undef regfree
#undef regerror

#include "btrc_win_regex_literal.h"

/* Both allocated representations have at least two-byte alignment. Tag the
   new pointer so an untagged regex_t from existing code stays usable, even
   when regcomp and regexec are compiled in different translation units. */
static inline int btrc_win_dispatch_regcomp(regex_t *restrict re, const char *restrict pattern, int flags)
{
	btrc_win_regex_simple *program = flags == REG_EXTENDED ? btrc_win_regex_compile_simple(pattern) : NULL;
	if (program) {
		memset(re, 0, sizeof *re);
		re->__opaque = (void *)((uintptr_t)program | (uintptr_t)1);
		return 0;
	}
	return btrc_win_legacy_regcomp(re, pattern, flags);
}

static inline int btrc_win_dispatch_regexec(const regex_t *restrict re, const char *restrict subject,
                                            size_t count, regmatch_t *restrict matches, int flags)
{
	uintptr_t pointer = (uintptr_t)re->__opaque;
	if (!(pointer & (uintptr_t)1)) return btrc_win_legacy_regexec(re, subject, count, matches, flags);
	const btrc_win_regex_simple *program = (const btrc_win_regex_simple *)(pointer - 1);
	if (!program->length && !program->at_start && !program->at_end) return btrc_win_regex_match_atom(&program->atom, subject, count, matches);
	return btrc_win_regex_match_literal(program, subject, count, matches, flags);
}

static inline void btrc_win_dispatch_regfree(regex_t *re)
{
	uintptr_t pointer = (uintptr_t)re->__opaque;
	if (pointer & (uintptr_t)1) {
		free((void *)(pointer - 1));
		re->__opaque = NULL;
	} else {
		btrc_win_legacy_regfree(re);
	}
}

#define regcomp btrc_win_dispatch_regcomp
#define regexec btrc_win_dispatch_regexec
#define regfree btrc_win_dispatch_regfree
#define regerror btrc_win_legacy_regerror
