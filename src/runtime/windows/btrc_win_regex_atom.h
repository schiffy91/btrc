/* Windows POSIX EREs consisting of one byte set and at most one simple
   quantifier. Concatenation, captures, assertions, extended options and
   diagnostics still belong to the complete provider. */
#pragma once
#include "btrc_win_match_bytes.h"

typedef struct {
	btrc_win_byte_set bytes;
	int minimum, maximum; /* A negative maximum allows any run length. */
} btrc_win_regex_atom;

/* Return the decimal bound, or -1 to leave diagnostics to the complete
   provider. The Windows C-locale RE_DUP_MAX is 255. */
static inline int btrc_win_regex_bound(const unsigned char **cursor)
{
	const unsigned char *p = *cursor;
	if (*p < '0' || *p > '9') return -1;
	int bound = 0;
	while (*p >= '0' && *p <= '9') {
		bound = 10 * bound + (*p++ - '0');
		if (bound > 255) return -1;
	}
	*cursor = p;
	return bound;
}

static inline int btrc_win_regex_parse_atom(const unsigned char *p, const unsigned char *end, btrc_win_regex_atom *atom)
{
	if (p == end) return 0;
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
	atom->minimum = atom->maximum = 1;
	if (p == end) return 1;
	if (p > end) return 0;
	if (*p == '{') {
		++p;
		atom->minimum = btrc_win_regex_bound(&p);
		if (atom->minimum < 0) return 0;
		atom->maximum = atom->minimum;
		if (*p == ',') {
			++p;
			if (*p == '}') atom->maximum = -1;
			else {
				atom->maximum = btrc_win_regex_bound(&p);
				if (atom->maximum < atom->minimum) return 0;
			}
		}
		return p[0] == '}' && p + 1 == end;
	}
	if (p + 1 != end || (*p != '+' && *p != '*' && *p != '?')) return 0;
	atom->minimum = *p == '+' ? 1 : 0;
	atom->maximum = *p == '?' ? 1 : -1;
	return 1;
}

static inline void btrc_win_regex_set_span(regmatch_t *matches, size_t count, regoff_t start, regoff_t end)
{
	matches[0] = (regmatch_t){start, end};
	for (size_t g = 1; g < count; ++g) matches[g] = (regmatch_t){-1, -1};
}

static inline int btrc_win_regex_match_atom(const btrc_win_regex_atom *atom, const char *subject,
                                            size_t count, regmatch_t *matches, int at_start, int at_end)
{
	const unsigned char *text = (const unsigned char *)subject;
	if (at_end) {
		const unsigned char *end = text + strlen(subject);
		const unsigned char *start = end;
		while (start > text && (atom->maximum < 0 || end - start < atom->maximum) &&
		       btrc_win_set_has(&atom->bytes, start[-1])) --start;
		if (end - start < atom->minimum || (at_start && start != text)) return REG_NOMATCH;
		if (count) btrc_win_regex_set_span(matches, count, start - text, end - text);
		return 0;
	}
	const unsigned char *start = text;
	int limit = count ? atom->maximum : atom->minimum;
	for (;;) {
		if (atom->minimum && !at_start) {
			while (*start && !btrc_win_set_has(&atom->bytes, *start)) ++start;
			if (!*start) return REG_NOMATCH;
		}
		const unsigned char *end = start;
		while (*end && (limit < 0 || end - start < limit) && btrc_win_set_has(&atom->bytes, *end)) ++end;
		if (end - start >= atom->minimum) {
			if (count) btrc_win_regex_set_span(matches, count, start - text, end - text);
			return 0;
		}
		if (at_start || !*end) return REG_NOMATCH;
		/* Every suffix of this short run is too short as well. */
		start = end + 1;
	}
}
