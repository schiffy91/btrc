/* Windows POSIX EREs consisting of one byte set and at most one simple
   quantifier. Concatenation, captures, assertions, extended options and
   diagnostics still belong to the complete provider. */
#pragma once
#include "btrc_win_match_bytes.h"

typedef struct {
	btrc_win_byte_set bytes;
	int optional, repeated;
} btrc_win_regex_atom;

static inline int btrc_win_regex_parse_atom(const char *pattern, btrc_win_regex_atom *atom)
{
	const unsigned char *p = (const unsigned char *)pattern;
	if (!*p) return 0;
	if (*p == '[') {
		const unsigned char *first = ++p;
		if (btrc_win_parse_list(&p, &atom->bytes, 0, 0) != btrc_win_list_ok) return 0;
		/* An excessive number of named classes in a negated bracket has
		   an existing resource diagnostic. Preserve it in the fallback. */
		if (*first == '^') {
			int classes = 0;
			for (const unsigned char *c = first; c + 1 < p; ++c)
				if (c[0] == '[' && c[1] == ':' && ++classes > 64) return 0;
		}
	} else if (*p == '.') {
		memset(&atom->bytes, 255, sizeof atom->bytes);
		++p;
	} else {
		if (strchr("\\^$*+?{}()|", *p)) return 0;
		btrc_win_set_add(&atom->bytes, *p++);
	}
	if (!*p) return 1;
	if (p[1] || (*p != '+' && *p != '*' && *p != '?')) return 0;
	atom->optional = *p != '+';
	atom->repeated = *p != '?';
	return 1;
}

static inline void btrc_win_regex_set_span(regmatch_t *matches, size_t count, regoff_t start, regoff_t end)
{
	matches[0] = (regmatch_t){start, end};
	for (size_t g = 1; g < count; ++g) matches[g] = (regmatch_t){-1, -1};
}

static inline int btrc_win_regex_match_atom(const btrc_win_regex_atom *atom, const char *subject,
                                            size_t count, regmatch_t *matches)
{
	const unsigned char *text = (const unsigned char *)subject;
	const unsigned char *start = text;
	if (!atom->optional) {
		while (*start && !btrc_win_set_has(&atom->bytes, *start)) ++start;
		if (!*start) return REG_NOMATCH;
	}
	if (!count) return 0;
	const unsigned char *end = start;
	while (*end && btrc_win_set_has(&atom->bytes, *end)) {
		++end;
		if (!atom->repeated) break;
	}
	btrc_win_regex_set_span(matches, count, start - text, end - text);
	return 0;
}
