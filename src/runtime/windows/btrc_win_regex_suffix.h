/* Windows capture ranking for (A)+B{m,n}, with A and B byte atoms and a
   finite, positive suffix length. */
#pragma once
#include "btrc_win_regex_atom.h"

typedef struct {
	btrc_win_group_header header;
	btrc_win_byte_set prefix;
	btrc_win_regex_atom suffix;
} btrc_win_regex_suffix;

static inline btrc_win_regex_suffix *btrc_win_regex_compile_suffix(const char *pattern)
{
	if (strlen(pattern) > 255) return NULL;
	const char *close = strstr(pattern, ")+");
	if (!close) return NULL;
	btrc_win_regex_atom atom = {0}, suffix = {0};
	const unsigned char *p = (const unsigned char *)pattern;
	if (!btrc_win_regex_parse_atom(p + 1, (const unsigned char *)close, &atom) ||
	    atom.minimum != 1 || atom.maximum != 1 ||
	    !btrc_win_regex_parse_atom((const unsigned char *)close + 2, p + strlen(pattern), &suffix) ||
	    suffix.minimum < 1 || suffix.maximum < suffix.minimum) return NULL;
	btrc_win_regex_suffix *result = (btrc_win_regex_suffix *)malloc(sizeof *result);
	if (result) *result = (btrc_win_regex_suffix){{btrc_win_group_suffix}, atom.bytes, suffix};
	return result;
}

static inline int btrc_win_regex_match_suffix(const btrc_win_regex_suffix *p, const char *subject,
                                             size_t count, regmatch_t *matches)
{
	/* At byte end e, p->suffix can begin at a split h between e-max and
	   e-min in the current suffix-byte run. Each split stores the start
	   of its preceding prefix run. Possible origins are nondecreasing;
	   adjacent splits with the same origin are the rival captures. */
	regoff_t origins[256], origin = -1, suffix_run = 0, first = 0, last = 0;
	regoff_t start = -1, end = 0, capture_end = 0;
	for (regoff_t i = 0; subject[i]; ++i) {
		unsigned char byte = (unsigned char)subject[i];
		origins[(size_t)i % 256] = origin;
		if (!btrc_win_set_has(&p->suffix.bytes, byte)) suffix_run = i + 1;
		if (!btrc_win_set_has(&p->prefix, byte)) origin = -1;
		else if (origin < 0 && start < 0) origin = i;

		regoff_t low = i + 1 - p->suffix.maximum, high = i + 1 - p->suffix.minimum;
		if (first < low) first = low;
		if (first < suffix_run) first = suffix_run;
		while (first <= high && origins[(size_t)first % 256] < 0) ++first;
		if (first > high) continue;
		if (!count) return 0;
		regoff_t earliest = origins[(size_t)first % 256];
		if (last < first) last = first;
		while (last < high && origins[(size_t)(last + 1) % 256] == earliest) ++last;

		/* A second, better subgroup at this end replaces the previous
		   whole match in the Windows dialect, even if its start is later. */
		if (start < 0 || earliest <= start || last > first) {
			start = earliest;
			end = i + 1;
			capture_end = last;
		}
	}
	if (start < 0) return REG_NOMATCH;
	btrc_win_regex_set_span(matches, count, start, end);
	if (count > 1) matches[1] = (regmatch_t){capture_end - 1, capture_end};
	return 0;
}
