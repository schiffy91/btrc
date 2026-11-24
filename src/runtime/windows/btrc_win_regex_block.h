/* End offsets for a repeated capture that may take one or more equal-width
   byte blocks. Windows may replace an older whole match when a second
   decomposition of the same prefix supplies a better subgroup. */
#pragma once
#include "btrc_win_regex_compile.h"

typedef struct {
	int width, check_other;
	btrc_win_byte_set byte, other;
} btrc_win_rx_blocks;

static inline int btrc_win_rx_unwrap(const btrc_win_rx_node *nodes, int n)
{
	while (n && nodes[n].op == btrc_win_rx_group && !nodes[n].next) n = nodes[n].child;
	return n;
}

static inline int btrc_win_rx_byte_before_bol(const btrc_win_rx_node *nodes, int n)
{
	n = btrc_win_rx_unwrap(nodes, n);
	if (!n || nodes[n].op != btrc_win_rx_byte) return 0;
	n = nodes[n].next;
	return n && !nodes[n].next && nodes[n].op == btrc_win_rx_assert && nodes[n].arg == btrc_win_rx_bol;
}

static inline void btrc_win_rx_detect_blocks(btrc_win_rx_blocks *result, const btrc_win_rx_node *nodes, int root)
{
	int n = btrc_win_rx_unwrap(nodes, root);
	if (!n || nodes[n].next || nodes[n].op != btrc_win_rx_repeat || nodes[n].min != 1 || nodes[n].max >= 0) return;
	n = btrc_win_rx_unwrap(nodes, nodes[n].child);
	if (n && !nodes[n].next && nodes[n].op == btrc_win_rx_choice) {
		/* A leading alternative that cannot consume anywhere in this
		   subject leaves only the bounded block. A following alternative
		   can share a position with the expanded repeat and stays legacy. */
		int tail = nodes[n].arg, other = btrc_win_rx_unwrap(nodes, nodes[n].child);
		if (!tail || nodes[tail].arg || !other || nodes[other].next || nodes[other].op != btrc_win_rx_byte) return;
		result->check_other = 1;
		result->other = nodes[other].bytes;
		n = btrc_win_rx_unwrap(nodes, nodes[tail].child);
	}
	if (!n || nodes[n].next || nodes[n].op != btrc_win_rx_repeat || nodes[n].min != 1 || nodes[n].max < 2 ||
	    nodes[nodes[n].child].op != btrc_win_rx_group) return;
	n = btrc_win_rx_unwrap(nodes, nodes[n].child);
	if (n && !nodes[n].next && nodes[n].op == btrc_win_rx_choice) {
		int tail = nodes[n].arg;
		if (!tail || nodes[tail].arg || result->check_other) return;
		if (btrc_win_rx_byte_before_bol(nodes, nodes[tail].child)) n = nodes[n].child;
		else if (btrc_win_rx_byte_before_bol(nodes, nodes[n].child)) n = nodes[tail].child;
		else return;
		n = btrc_win_rx_unwrap(nodes, n);
	}
	if (!n) return;
	int width = 0;
	if (!nodes[n].next && nodes[n].op == btrc_win_rx_repeat) {
		if (nodes[n].min != nodes[n].max || nodes[n].min < 2) return;
		width = nodes[n].min;
		n = btrc_win_rx_unwrap(nodes, nodes[n].child);
		if (!n || nodes[n].next || nodes[n].op != btrc_win_rx_byte || nodes[n].copy_stride != 1) return;
	} else {
		for (int i = n; i; i = nodes[i].next) {
			if (nodes[i].op != btrc_win_rx_byte || nodes[i].copy_stride != 1 ||
			    memcmp(&nodes[n].bytes, &nodes[i].bytes, sizeof nodes[i].bytes)) return;
			++width;
		}
	}
	if (width >= 2) { result->width = width; result->byte = nodes[n].bytes; }
}

/* The first complete block wins until a second complete block is present.
   After that, both a continuation of the inner repeat and a new outer
   repetition can accept. Their capture ranking lets the final partial
   block shift the start forward without changing the consumed length. */
static inline int btrc_win_rx_block_match(const btrc_win_rx_blocks *blocks, const char *subject, regmatch_t *match)
{
	const unsigned char *s = (const unsigned char *)subject;
	if (!blocks->width) return btrc_win_pos_competing_starts;
	if (blocks->check_other)
		for (const unsigned char *c = s; *c; ++c) if (btrc_win_set_has(&blocks->other, *c)) return btrc_win_pos_competing_starts;
	while (*s) {
		if (!btrc_win_set_has(&blocks->byte, *s)) { ++s; continue; }
		const unsigned char *first = s;
		do ++s; while (*s && btrc_win_set_has(&blocks->byte, *s));
		regoff_t length = s - first;
		if (length < blocks->width) continue;
		regoff_t delta = length % blocks->width;
		regoff_t start = first - (const unsigned char *)subject;
		if (length < 2 * blocks->width) *match = (regmatch_t){start, start + blocks->width};
		else *match = (regmatch_t){start + delta, start + length};
		return 0;
	}
	return REG_NOMATCH;
}
