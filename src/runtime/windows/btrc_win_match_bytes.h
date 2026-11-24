/* C-locale byte sets shared by the Windows pattern and regex interfaces. */
#pragma once

#include <stddef.h>
#include <string.h>

typedef struct { unsigned char bits[32]; } btrc_win_byte_set;

static inline unsigned int btrc_win_fold(unsigned int b)
{
	return b >= 'A' && b <= 'Z' ? b + ('a' - 'A') : b;
}

static inline int btrc_win_word(unsigned int b)
{
	unsigned int lower = btrc_win_fold(b);
	return (lower >= 'a' && lower <= 'z') || (b >= '0' && b <= '9') || b == '_';
}

static inline void btrc_win_set_add(btrc_win_byte_set *set, unsigned int b)
{
	set->bits[b / 8] |= (unsigned char)(1u << (b % 8));
}

static inline int btrc_win_set_has(const btrc_win_byte_set *set, unsigned int b)
{
	return (set->bits[b / 8] >> (b % 8)) & 1;
}

static inline void btrc_win_set_finish(btrc_win_byte_set *set, int fold, int negate)
{
	if (fold) {
		for (unsigned int i = 'A'; i <= 'Z'; ++i) {
			if (btrc_win_set_has(set, i) || btrc_win_set_has(set, btrc_win_fold(i))) {
				btrc_win_set_add(set, i);
				btrc_win_set_add(set, btrc_win_fold(i));
			}
		}
	}
	if (negate) for (size_t i = 0; i < sizeof set->bits; ++i) set->bits[i] ^= 255;
}

static inline int btrc_win_set_class(btrc_win_byte_set *set, const unsigned char *name, size_t len)
{
	static const char *const names[] = {
		"alnum", "alpha", "blank", "cntrl", "digit", "graph", "lower",
		"print", "punct", "space", "upper", "xdigit"
	};
	size_t kind = 0;
	while (kind < sizeof names / sizeof *names &&
	       (strlen(names[kind]) != len || memcmp(names[kind], name, len) != 0)) ++kind;
	if (kind == sizeof names / sizeof *names) return 0;
	for (unsigned int i = 0; i < 128; ++i) {
		int upper = i >= 'A' && i <= 'Z';
		int lower = i >= 'a' && i <= 'z';
		int digit = i >= '0' && i <= '9';
		int alpha = upper || lower;
		int graph = i > ' ' && i < 127;
		int classes[] = {alpha || digit, alpha, i == ' ' || i == '\t', i < 32 || i == 127,
		                 digit, graph, lower, i >= ' ' && i < 127, graph && !alpha && !digit,
		                 i == ' ' || (i >= '\t' && i <= '\r'), upper,
		                 digit || (btrc_win_fold(i) >= 'a' && btrc_win_fold(i) <= 'f')};
		if (classes[kind]) btrc_win_set_add(set, i);
	}
	return 1;
}

/* The caller decides how to report a malformed list. Wildcard patterns
   treat a missing closing bracket as a literal opening bracket. */
enum btrc_win_list_error {
	btrc_win_list_ok, btrc_win_list_unclosed, btrc_win_list_range,
	btrc_win_list_class, btrc_win_list_collate
};

static inline enum btrc_win_list_error btrc_win_parse_list(
	const unsigned char **after, btrc_win_byte_set *set, int shell, int fold, int *copy_stride)
{
	const unsigned char *p = *after;
	int negate = *p == '^' || (shell && *p == '!');
	if (negate) ++p;
	int terms = 0;
	btrc_win_byte_set named = {0};
	int previous = -1;
	int range = 0;
	do {
		if (!*p) return btrc_win_list_unclosed;
		if (!shell && *p == '-' && previous >= 0 && !p[1]) return btrc_win_list_range;
		if (*p == '-' && previous >= 0 && p[1] && p[1] != ']') {
			++p;
			range = 1;
		}
		/* A regex range ends in one literal byte, including '['. */
		if (copy_stride && !range) ++terms;
		if ((!range || shell) && p[0] == '[' && (p[1] == ':' || p[1] == '.' || p[1] == '=')) {
			unsigned char type = p[1];
			const unsigned char *name = p + 2;
			const unsigned char *end = name;
			while (*end && !(end[0] == type && end[1] == ']')) ++end;
			if (!*end) return btrc_win_list_unclosed;
			if (type == ':') {
				if (!btrc_win_set_class(copy_stride && negate ? &named : set, name, (size_t)(end - name)) && !shell) return btrc_win_list_class;
			} else if (!shell) return btrc_win_list_collate;
			previous = -1;
			p = end + 2;
		} else {
			int c = *p++;
			if (range) {
				if (previous > c && !shell) return btrc_win_list_range;
				for (int i = previous; i < c; ++i) btrc_win_set_add(set, (unsigned int)i);
			}
			btrc_win_set_add(set, (unsigned int)c);
			previous = range && !shell ? -1 : c;
		}
		/* A completed range or named class cannot start a second range.
		   Windows also accepts a new range with '-' as its lower endpoint,
		   as in [a-z--@], where the second range is '-' through '@'. */
		if (!shell && previous < 0 && p[0] == '-' && p[1] != ']' &&
		    (p[1] != '-' || !p[2] || p[2] == ']')) return btrc_win_list_range;
		range = 0;
	} while (*p != ']');
	if (copy_stride) {
		if (negate) {
			/* Negating the explicit ranges creates one extra gap per
			   disjoint excluded run. Named exclusions filter every gap. */
			terms = 1;
			int previous_byte = 0;
			for (unsigned int byte = 1; byte <= 255; ++byte) {
				int excluded = btrc_win_set_has(set, byte);
				if (excluded && !previous_byte) ++terms;
				previous_byte = excluded;
			}
			for (size_t i = 0; i < sizeof set->bits; ++i) set->bits[i] |= named.bits[i];
		}
		*copy_stride = terms;
	}
	btrc_win_set_finish(set, fold, negate);
	*after = p + 1;
	return btrc_win_list_ok;
}
