/* POSIX shell patterns for the Windows overlay, operating on C-locale bytes. */
#pragma once

#define FNM_PATHNAME    0x1
#define FNM_NOESCAPE    0x2
#define FNM_PERIOD      0x4
#define FNM_LEADING_DIR 0x8
#define FNM_CASEFOLD    0x10
#define FNM_FILE_NAME   FNM_PATHNAME

#define FNM_NOMATCH 1
#define FNM_NOSYS   (-1)

#include "btrc_win_match_bytes.h"

/* Each star has the same alphabet within one pathname component. Once a
   later star is reached, it can absorb any extra bytes the earlier one
   could have absorbed. Only the most recent retry position is needed. */
static inline int btrc_win_fnmatch(const char *pattern, const char *text, int flags)
{
	const unsigned char *p = (const unsigned char *)pattern;
	const unsigned char *s = (const unsigned char *)text;
	const unsigned char *star = NULL, *retry = NULL;
	int pathname = flags & FNM_PATHNAME;
	int fold = flags & FNM_CASEFOLD;
	for (;;) {
		if ((flags & FNM_PERIOD) && *s == '.' &&
		    (s == (const unsigned char *)text || (pathname && s[-1] == '/')) && *p != '.') return FNM_NOMATCH;
		if (*p == '*') {
			do ++p; while (*p == '*');
			star = p;
			retry = s;
			continue;
		}
		if (!*p && (!*s || ((flags & FNM_LEADING_DIR) && *s == '/'))) return 0;
		if (*s && *p) {
			const unsigned char *next = p + 1;
			int match;
			if (*p == '?') match = !pathname || *s != '/';
			else if (*p == '[') {
				btrc_win_byte_set set = {{0}};
				enum btrc_win_list_error error = btrc_win_parse_list(&next, &set, 1, fold, NULL);
				match = error == btrc_win_list_ok ? ((!pathname || *s != '/') && btrc_win_set_has(&set, *s)) : *s == '[';
			} else {
				unsigned char c = *p;
				if (c == '\\' && !(flags & FNM_NOESCAPE) && *next) c = *next++;
				match = fold ? btrc_win_fold(c) == btrc_win_fold(*s) : c == *s;
			}
			if (match) {
				if (pathname && *s == '/') star = NULL;
				p = next;
				++s;
				continue;
			}
		}
		if (!star || !*retry || (pathname && *retry == '/')) return FNM_NOMATCH;
		p = star;
		s = ++retry;
	}
}

#define fnmatch btrc_win_fnmatch
