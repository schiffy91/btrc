/* Capture ranking for a repeated byte group followed by a bounded,
   positive byte suffix. The prefix may be required or bounded and nullable. */
#pragma once
#include "btrc_win_regex_atom.h"
#include "btrc_win_regex_compile.h"

typedef struct {
	btrc_win_byte_set prefix;
	btrc_win_regex_atom suffix;
	int optional_prefix_limit;
} btrc_win_suffix_span;

typedef struct {
	btrc_win_group_header header;
	btrc_win_suffix_span span;
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
	if (result) *result = (btrc_win_regex_suffix){{btrc_win_group_suffix}, {atom.bytes, suffix, 0}};
	return result;
}

static inline int btrc_win_regex_match_suffix(const btrc_win_suffix_span *p, const char *subject,
                                             size_t count, regmatch_t *matches)
{
	/* At byte end e, p->suffix can begin at a split h between e-max and
	   e-min in the current suffix-byte run. Each split stores the start
	   of its preceding prefix run. Possible origins are nondecreasing;
	   adjacent splits with the same origin are the rival captures. */
	regoff_t origins[256], origin = -1, suffix_run = 0, first = 0, last = 0;
	regoff_t start = -1, end = 0, capture_end = 0, prefix_start = 0, first_end = -1;
	for (regoff_t i = 0; subject[i]; ++i) {
		unsigned char byte = (unsigned char)subject[i];
		int prefix_byte = btrc_win_set_has(&p->prefix, byte);
		if (p->optional_prefix_limit) {
			/* A nullable prefix can start at the split itself. Stop admitting
			   new starts once the earliest complete match has been observed. */
			regoff_t earliest = i - p->optional_prefix_limit;
			if (earliest < prefix_start) earliest = prefix_start;
			origins[(size_t)i % 256] = first_end < 0 || earliest < first_end ? earliest : -1;
			if (!prefix_byte) prefix_start = i + 1;
		} else {
			origins[(size_t)i % 256] = origin;
			if (!prefix_byte) origin = -1;
			else if (origin < 0 && start < 0) origin = i;
		}
		if (!btrc_win_set_has(&p->suffix.bytes, byte)) suffix_run = i + 1;

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
			if (first_end < 0) first_end = end;
			capture_end = last;
		}
	}
	if (start < 0) return REG_NOMATCH;
	btrc_win_regex_set_span(matches, count, start, end);
	if (count > 1) matches[1] = (regmatch_t){capture_end - 1, capture_end};
	return 0;
}

/* A{0,k} before a positive counted suffix can admit an empty prefix
   at each start until the first acceptance. Capture wrappers decide
   whether competing split points may replace an older whole match.
   Recognized prefix forms are (A){0,k}, ((A){0,k})?, ((A)?){k}
   and (((A)?){k})?. Remaining group layouts retain their normal route. */
static inline void btrc_win_rx_detect_optional_suffix(btrc_win_suffix_span *span,
                                                     const btrc_win_rx_node *nodes, int root)
{
	if (!root || nodes[root].op != btrc_win_rx_repeat) return;
	int tail = nodes[root].next;
	if (!tail || nodes[tail].next || nodes[tail].op != btrc_win_rx_repeat ||
	    nodes[tail].min < 1 || nodes[tail].max < nodes[tail].min) return;
	int last = nodes[tail].child;
	if (nodes[last].op == btrc_win_rx_group) last = nodes[last].child;
	if (!last || nodes[last].next || nodes[last].op != btrc_win_rx_byte) return;
	int prefix = root, group = nodes[prefix].child;
	if (nodes[prefix].min == 0 && nodes[prefix].max == 1 && nodes[group].op == btrc_win_rx_group &&
	    nodes[group].child && !nodes[nodes[group].child].next && nodes[nodes[group].child].op == btrc_win_rx_repeat) {
		prefix = nodes[group].child;
		group = nodes[prefix].child;
	}
	if (nodes[group].op != btrc_win_rx_group) return;
	int atom = nodes[group].child;
	if (!atom || nodes[atom].next) return;
	int limit = nodes[prefix].max;
	if (nodes[prefix].min > 0) {
		if (nodes[prefix].min != limit || nodes[atom].op != btrc_win_rx_repeat ||
		    nodes[atom].min != 0 || nodes[atom].max != 1) return;
		group = nodes[atom].child;
		if (nodes[group].op != btrc_win_rx_group) return;
		atom = nodes[group].child;
	}
	if (limit < 1 || !atom || nodes[atom].next || nodes[atom].op != btrc_win_rx_byte) return;
	*span = (btrc_win_suffix_span){nodes[atom].bytes, {nodes[last].bytes, nodes[tail].min, nodes[tail].max}, limit};
}
