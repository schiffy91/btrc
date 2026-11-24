/* A word boundary competes with a bounded repetition of nullable byte
   captures and fixed-width byte blocks. If the optional byte is absent,
   only whole blocks and the boundary can reach the end of a match. */
#pragma once
#include "btrc_win_regex_block.h"

typedef struct {
	btrc_win_byte_set optional, block;
	int assertion, width, minimum, maximum;
} btrc_win_boundary_blocks;

static inline int btrc_win_rx_two_arms(const btrc_win_rx_node *nodes, int n)
{
	return n && !nodes[n].next && nodes[n].op == btrc_win_rx_choice &&
	       nodes[n].arg && !nodes[nodes[n].arg].arg;
}

static inline int btrc_win_rx_detect_boundary_blocks(btrc_win_boundary_blocks *result,
                                                     const btrc_win_rx_node *nodes, int root)
{
	int choice = btrc_win_rx_unwrap(nodes, root);
	if (!btrc_win_rx_two_arms(nodes, choice)) return 0;
	int first = nodes[choice].child;
	int repeat = btrc_win_rx_unwrap(nodes, nodes[nodes[choice].arg].child);
	if (!first || nodes[first].next || nodes[first].op != btrc_win_rx_assert ||
	    (nodes[first].arg != btrc_win_rx_nonboundary && nodes[first].arg != btrc_win_rx_word_boundary) ||
	    !repeat || nodes[repeat].next || nodes[repeat].op != btrc_win_rx_repeat ||
	    nodes[repeat].min < 1 || nodes[repeat].max < nodes[repeat].min) return 0;
	choice = btrc_win_rx_unwrap(nodes, nodes[repeat].child);
	if (!btrc_win_rx_two_arms(nodes, choice)) return 0;
	int opt = nodes[choice].child, fixed = nodes[nodes[choice].arg].child;
	if (!opt || nodes[opt].next || nodes[opt].op != btrc_win_rx_repeat || nodes[opt].min || nodes[opt].max < 1 ||
	    !fixed || nodes[fixed].next || nodes[fixed].op != btrc_win_rx_repeat ||
	    nodes[fixed].min < 1 || nodes[fixed].min != nodes[fixed].max ||
	    nodes[repeat].max * (nodes[opt].max + nodes[fixed].max) > 127) return 0;
	if (nodes[nodes[opt].child].op != btrc_win_rx_group || nodes[nodes[fixed].child].op != btrc_win_rx_group) return 0;
	int a = nodes[nodes[opt].child].child, b = nodes[nodes[fixed].child].child;
	if (!a || nodes[a].next || nodes[a].op != btrc_win_rx_byte ||
	    !b || nodes[b].next || nodes[b].op != btrc_win_rx_byte) return 0;
	*result = (btrc_win_boundary_blocks){nodes[a].bytes, nodes[b].bytes, nodes[first].arg,
	                                    nodes[fixed].min, nodes[repeat].min, nodes[repeat].max};
	return 1;
}

static inline int btrc_win_rx_match_boundary_blocks(const btrc_win_boundary_blocks *p, const char *subject,
                                                    size_t count, regmatch_t *matches)
{
	const unsigned char *s = (const unsigned char *)subject;
	regoff_t start = -1, end = -1, admitted = 0, run = 0;
	for (regoff_t i = 0;; ++i) {
		if (start < 0) {
			admitted = i;
			int boundary = !i || !s[i] || btrc_win_word(s[i - 1]) != btrc_win_word(s[i]);
			if (boundary == (p->assertion == btrc_win_rx_word_boundary)) start = end = i;
		}
		/* Earliest admitted origin that reaches i via whole blocks. A
		   trailing empty mandatory repetition gives a competing final
		   capture that can overwrite an earlier winning origin. */
		regoff_t blocks = (i - run) / p->width;
		if (blocks > p->maximum) blocks = p->maximum;
		regoff_t origin = i - blocks * p->width;
		if (blocks && origin <= admitted && (start < 0 || origin <= start || blocks < p->minimum)) {
			if (start < 0) admitted = i - 1;
			start = origin;
			end = i;
		}
		if (!s[i]) break;
		if (s[i] >= 128 || btrc_win_set_has(&p->optional, s[i])) return btrc_win_pos_competing_starts;
		if (!btrc_win_set_has(&p->block, s[i])) run = i + 1;
	}
	if (start < 0) return REG_NOMATCH;
	if (count) btrc_win_regex_set_span(matches, count, start, end);
	return 0;
}
