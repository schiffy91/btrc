/* First-party POSIX <regex.h> for the MinGW-w64 Windows rows (windows-x86_64,
   windows-aarch64). MinGW-w64 ships no regular-expression engine.

   This header declares the POSIX interface and compiles the first-party C11
   engine into the including translation unit with internal linkage, so every
   build that already puts this overlay on its include path (Makefile
   WIN_COMPAT, tools/native_plan.py, the target runner, windows.yml) links it
   without a separate object, and several units of one program each keep a
   private copy while sharing compiled regex_t handles cleanly.

   Matching follows the C locale every btrc program runs in: each byte is one
   character, and character classes and REG_ICASE cover ASCII only. */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

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

#include "btrc_win_regex_literal.h"
#include "btrc_win_regex_compile.h"
#include "btrc_win_regex_exec.h"

/* Generated programs can call regexec/regfree from a different translation
   unit. Tag allocated pointers in bit 0 (fast literal/atom vs general NFA)
   without altering regex_t layout. */
static inline int btrc_win_regcomp(regex_t *restrict re, const char *restrict pattern, int flags)
{
	if (!re || !pattern) return REG_BADPAT;
	memset(re, 0, sizeof *re);
	if ((flags & ~REG_NOSUB) == REG_EXTENDED) {
		btrc_win_regex_simple *simple = btrc_win_regex_compile_simple(pattern, flags);
		if (simple) {
			re->__opaque = (void *)((uintptr_t)simple | (uintptr_t)1);
			return 0;
		}
	}
	btrc_win_rx_program *rx = NULL;
	size_t nsub = 0;
	int status = btrc_win_rx_compile(&rx, &nsub, pattern, flags);
	if (status) return status;
	re->re_nsub = nsub;
	re->__opaque = (void *)rx;
	return 0;
}

static inline int btrc_win_regexec(const regex_t *restrict re, const char *restrict subject,
                                   size_t count, regmatch_t *restrict matches, int flags)
{
	if (!re || !re->__opaque || !subject) return REG_BADPAT;
	uintptr_t pointer = (uintptr_t)re->__opaque;
	if (pointer & (uintptr_t)1) {
		const btrc_win_regex_simple *simple = (const btrc_win_regex_simple *)(pointer - 1);
		if (simple->flags & REG_NOSUB) count = 0;
		if ((simple->at_start && (flags & REG_NOTBOL)) || (simple->at_end && (flags & REG_NOTEOL)))
			return REG_NOMATCH;
		if (simple->is_atom)
			return btrc_win_regex_match_atom(&simple->atom, subject, count, matches,
			                                 simple->at_start, simple->at_end);
		return btrc_win_regex_match_literal(simple, subject, count, matches);
	}
	return btrc_win_rx_exec((const btrc_win_rx_program *)pointer, subject, count, matches, flags);
}

static inline void btrc_win_regfree(regex_t *re)
{
	if (!re || !re->__opaque) return;
	uintptr_t pointer = (uintptr_t)re->__opaque;
	if (pointer & (uintptr_t)1) free((void *)(pointer - 1));
	else btrc_win_rx_free((btrc_win_rx_program *)pointer);
	re->__opaque = NULL;
}

/* C-locale diagnostic messages and POSIX regerror buffer-sizing semantics. */
static inline size_t btrc_win_regerror(int code, const regex_t *restrict compiled,
                                       char *restrict buffer, size_t capacity)
{
	static const char *const btrc_win_regex_diagnostics[] = {
		[REG_OK] = "No error",
		[REG_NOMATCH] = "No match",
		[REG_BADPAT] = "Invalid regexp",
		[REG_ECOLLATE] = "Unknown collating element",
		[REG_ECTYPE] = "Unknown character class name",
		[REG_EESCAPE] = "Trailing backslash",
		[REG_ESUBREG] = "Invalid back reference",
		[REG_EBRACK] = "Missing ']'",
		[REG_EPAREN] = "Missing ')'",
		[REG_EBRACE] = "Missing '}'",
		[REG_BADBR] = "Invalid contents of {}",
		[REG_ERANGE] = "Invalid character range",
		[REG_ESPACE] = "Out of memory",
		[REG_BADRPT] = "Repetition not preceded by valid expression",
	};
	(void)compiled;
	const char *description = (unsigned int)code <= REG_BADRPT ? btrc_win_regex_diagnostics[code] : "Unknown error";
	size_t length = strlen(description);
	if (capacity) {
		size_t copied = length < capacity ? length : capacity - 1;
		memcpy(buffer, description, copied);
		buffer[copied] = 0;
	}
	return length + 1;
}

#define regcomp btrc_win_regcomp
#define regexec btrc_win_regexec
#define regfree btrc_win_regfree
#define regerror btrc_win_regerror
