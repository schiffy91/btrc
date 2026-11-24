/* First-party POSIX regex execution engine for Windows:
   - Pass 1 (no backreferences): O(|code| * |text|) linear NFA simulation with
     sorted start origins for exact POSIX leftmost-longest [rm_so, rm_eo).
   - Pass 2 (submatches requested, no backreferences): exact backward-pruned
     top-down POSIX leftmost-longest submatch extractor on [first, last].
   - Pass 3 (BRE backreferences \1..\9, or >16 MiB Pass-2 workspace fallback):
     bounded tagged NFA with strict step and memory caps against ReDoS. */
#pragma once
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "btrc_win_regex_compile.h"

enum {
	btrc_win_rx_stack_code = 256,
	btrc_win_rx_live_limit = 16u * 1024u * 1024u,
	btrc_win_rx_frontier_limit = 16u * 1024u * 1024u,
	btrc_win_rx_total_work = 16000000u
};

static inline int btrc_win_rx_boundary_ok(int assertion, const unsigned char *s, regoff_t pos, int flags, int execflags)
{
	unsigned char c = s[pos];
	unsigned char prev = pos ? s[pos - 1] : 0;
	int word = btrc_win_word(c), previous = btrc_win_word(prev);
	switch (assertion) {
	case btrc_win_rx_bol: return (!pos && !(execflags & REG_NOTBOL)) || ((flags & REG_NEWLINE) && prev == '\n');
	case btrc_win_rx_eol: return (!c && !(execflags & REG_NOTEOL)) || ((flags & REG_NEWLINE) && c == '\n');
	case btrc_win_rx_bow: return word && !previous;
	case btrc_win_rx_eow: return !word && previous;
	case btrc_win_rx_word_boundary: return word != previous;
	default: return word == previous;
	}
}

/* ── Pass 1: O(|code| * |text|) leftmost-longest span finder ────────────── */

static inline void btrc_win_rx_close_span(const btrc_win_rx_program *rx, const unsigned char *s, regoff_t pos,
                                          int eflags, int root, regoff_t origin, regoff_t *now_start,
                                          int *closed_list, int *closed_count, unsigned char *closed_seen,
                                          regoff_t *first, regoff_t *last)
{
	int qhead = *closed_count;
	closed_seen[root] = 1;
	now_start[root] = origin;
	closed_list[(*closed_count)++] = root;
	while (qhead < *closed_count) {
		int pc = closed_list[qhead++];
		btrc_win_rx_inst in = rx->code[pc];
		int d1 = -1, d2 = -1;
		switch (in.op) {
		case btrc_win_rx_byte:
			continue;
		case btrc_win_rx_assert:
			if (!btrc_win_rx_boundary_ok(in.arg, s, pos, rx->flags, eflags)) continue;
			d1 = pc + 1;
			break;
		case btrc_win_rx_split:
			d1 = pc + 1;
			d2 = in.target;
			break;
		case btrc_win_rx_jump:
			d1 = in.target;
			break;
		case btrc_win_rx_open:
		case btrc_win_rx_close:
		case btrc_win_rx_mark:
		case btrc_win_rx_rank:
			d1 = pc + 1;
			break;
		case btrc_win_rx_accept:
			if (*first < 0 || origin < *first || (origin == *first && pos > *last)) {
				*first = origin;
				*last = pos;
			}
			continue;
		default:
			continue;
		}
		if (d1 >= 0 && !closed_seen[d1]) {
			closed_seen[d1] = 1;
			now_start[d1] = origin;
			closed_list[(*closed_count)++] = d1;
		}
		if (d2 >= 0 && !closed_seen[d2]) {
			closed_seen[d2] = 1;
			now_start[d2] = origin;
			closed_list[(*closed_count)++] = d2;
		}
	}
}

static inline int btrc_win_rx_find_span(const btrc_win_rx_program *rx, const unsigned char *s, int eflags,
                                        int want_span, regoff_t *out_first, regoff_t *out_last)
{
	int m = rx->code_count;
	regoff_t stack_starts[2 * btrc_win_rx_stack_code];
	int stack_lists[3 * btrc_win_rx_stack_code];
	unsigned char stack_seen[btrc_win_rx_stack_code];
	regoff_t *starts = stack_starts;
	int *lists = stack_lists;
	unsigned char *closed_seen = stack_seen;
	void *heap = NULL;
	if (m > btrc_win_rx_stack_code) {
		size_t sz_starts = 2u * (size_t)m * sizeof(regoff_t);
		size_t sz_lists = 3u * (size_t)m * sizeof(int);
		size_t sz_seen = (size_t)m;
		heap = malloc(sz_starts + sz_lists + sz_seen);
		if (!heap) return REG_ESPACE;
		starts = (regoff_t *)heap;
		lists = (int *)((unsigned char *)heap + sz_starts);
		closed_seen = (unsigned char *)heap + sz_starts + sz_lists;
	}
	regoff_t *now_start = starts;
	regoff_t *next_start = starts + m;
	int *now_list = lists;
	int *next_list = lists + m;
	int *closed_list = lists + 2 * m;
	for (int i = 0; i < m; ++i) {
		now_start[i] = next_start[i] = -1;
		closed_seen[i] = 0;
	}
	int now_count = 0;
	regoff_t first = -1, last = -1;
	for (regoff_t pos = 0;; ++pos) {
		int closed_count = 0;
		for (int idx = 0; idx < now_count; ++idx) {
			int root = now_list[idx];
			if (closed_seen[root]) continue;
			regoff_t origin = now_start[root];
			if (first >= 0 && origin > first) break;
			btrc_win_rx_close_span(rx, s, pos, eflags, root, origin, now_start,
			                       closed_list, &closed_count, closed_seen, &first, &last);
		}
		if (first < 0 && !closed_seen[0]) {
			btrc_win_rx_close_span(rx, s, pos, eflags, 0, pos, now_start,
			                       closed_list, &closed_count, closed_seen, &first, &last);
		}
		if ((first >= 0 && !want_span) || !s[pos]) break;
		int next_count = 0;
		unsigned char byte = s[pos];
		for (int idx = 0; idx < closed_count; ++idx) {
			int pc = closed_list[idx];
			regoff_t origin = now_start[pc];
			if (first >= 0 && origin > first) break;
			btrc_win_rx_inst in = rx->code[pc];
			if (in.op == btrc_win_rx_byte && btrc_win_set_has(&rx->nodes[in.arg].bytes, byte)) {
				int dst = pc + 1;
				if (next_start[dst] < 0) {
					next_start[dst] = origin;
					next_list[next_count++] = dst;
				}
			}
		}
		for (int idx = 0; idx < closed_count; ++idx) {
			int pc = closed_list[idx];
			closed_seen[pc] = 0;
			now_start[pc] = -1;
		}
		for (int idx = 0; idx < now_count; ++idx) now_start[now_list[idx]] = -1;
		if (first >= 0 && next_count == 0) break;
		regoff_t *swap_s = now_start;
		now_start = next_start;
		next_start = swap_s;
		int *swap_l = now_list;
		now_list = next_list;
		next_list = swap_l;
		now_count = next_count;
	}
	free(heap);
	if (first < 0) return REG_NOMATCH;
	*out_first = first;
	*out_last = last;
	return 0;
}

/* ── Pass 2: Exact POSIX leftmost-longest submatch extraction ───────────── */

typedef struct {
	const btrc_win_rx_program *rx;
	const unsigned char *s;
	int eflags;
	regmatch_t *groups;
	int *rev_head, *rev_from, *queue, *now_list, *next_list;
	unsigned int *seen;
	unsigned int gen;
} btrc_win_rx_extract_ctx;

typedef struct {
	int node;
	regoff_t start, end;
} btrc_win_rx_span_task;

static inline unsigned int btrc_win_rx_next_gen(btrc_win_rx_extract_ctx *ctx, int count)
{
	if (++ctx->gen == 0) {
		memset(ctx->seen, 0, (size_t)ctx->rx->code_count * sizeof *ctx->seen);
		ctx->gen = 1;
	}
	(void)count;
	return ctx->gen;
}

static inline int btrc_win_rx_bit_get(const unsigned char *bits, size_t row, size_t col, size_t width)
{
	size_t idx = row * width + col;
	return (bits[idx / 8] >> (idx % 8)) & 1;
}

static inline void btrc_win_rx_bit_set(unsigned char *bits, size_t row, size_t col, size_t width)
{
	size_t idx = row * width + col;
	bits[idx / 8] |= (unsigned char)(1u << (idx % 8));
}

static inline int btrc_win_rx_slice_matches(btrc_win_rx_extract_ctx *ctx, int lo, int hi, regoff_t i, regoff_t j)
{
	if (lo == hi) return i == j;
	const btrc_win_rx_program *rx = ctx->rx;
	int *now = ctx->now_list, *next = ctx->next_list, *queue = ctx->queue;
	int now_count = 1;
	now[0] = lo;
	for (regoff_t pos = i; pos <= j && now_count > 0; ++pos) {
		unsigned int g = btrc_win_rx_next_gen(ctx, hi - lo + 1);
		int qhead = 0, qtail = 0;
		for (int k = 0; k < now_count; ++k) {
			int pc = now[k];
			if (ctx->seen[pc - lo] != g) {
				ctx->seen[pc - lo] = g;
				queue[qtail++] = pc;
			}
		}
		while (qhead < qtail) {
			int pc = queue[qhead++];
			if (pc == hi) {
				if (pos == j) return 1;
				continue;
			}
			btrc_win_rx_inst in = rx->code[pc];
			int d1 = -1, d2 = -1;
			switch (in.op) {
			case btrc_win_rx_byte: continue;
			case btrc_win_rx_assert:
				if (!btrc_win_rx_boundary_ok(in.arg, ctx->s, pos, rx->flags, ctx->eflags)) continue;
				d1 = pc + 1;
				break;
			case btrc_win_rx_split: d1 = pc + 1; d2 = in.target; break;
			case btrc_win_rx_jump: d1 = in.target; break;
			case btrc_win_rx_open:
			case btrc_win_rx_close:
			case btrc_win_rx_mark:
			case btrc_win_rx_rank: d1 = pc + 1; break;
			default: continue;
			}
			if (d1 >= lo && d1 <= hi && ctx->seen[d1 - lo] != g) {
				ctx->seen[d1 - lo] = g;
				queue[qtail++] = d1;
			}
			if (d2 >= lo && d2 <= hi && ctx->seen[d2 - lo] != g) {
				ctx->seen[d2 - lo] = g;
				queue[qtail++] = d2;
			}
		}
		if (pos == j) return 0;
		int next_count = 0;
		unsigned int ng = btrc_win_rx_next_gen(ctx, hi - lo + 1);
		unsigned char byte = ctx->s[pos];
		for (int k = 0; k < qtail; ++k) {
			int pc = queue[k];
			if (pc >= hi) continue;
			btrc_win_rx_inst in = rx->code[pc];
			if (in.op == btrc_win_rx_byte && btrc_win_set_has(&rx->nodes[in.arg].bytes, byte)) {
				int dst = pc + 1;
				if (dst <= hi && ctx->seen[dst - lo] != ng) {
					ctx->seen[dst - lo] = ng;
					next[next_count++] = dst;
				}
			}
		}
		int *swap = now;
		now = next;
		next = swap;
		now_count = next_count;
	}
	return 0;
}

static inline int btrc_win_rx_backward(btrc_win_rx_extract_ctx *ctx, int lo, int hi, regoff_t i, regoff_t j,
                                       unsigned char **out_bits)
{
	*out_bits = NULL;
	const btrc_win_rx_program *rx = ctx->rx;
	size_t width = (size_t)(hi - lo + 1);
	size_t rows = (size_t)(j - i + 1);
	size_t max_bits = (size_t)btrc_win_rx_live_limit * 8u;
	if (rows > max_bits / width) return REG_ESPACE;
	size_t total_bits = rows * width;
	unsigned char *bits = (unsigned char *)calloc((total_bits + 7u) / 8u, 1);
	if (!bits) return REG_ESPACE;

	/* Build reverse epsilon CSR for code[lo .. hi - 1]. */
	int *head = ctx->rev_head;
	int *from = ctx->rev_from;
	int m = hi - lo + 1;
	for (int v = 0; v <= m; ++v) head[v] = 0;
	for (int u = 0; u < m - 1; ++u) {
		btrc_win_rx_inst in = rx->code[lo + u];
		switch (in.op) {
		case btrc_win_rx_assert:
		case btrc_win_rx_open:
		case btrc_win_rx_close:
		case btrc_win_rx_mark:
		case btrc_win_rx_rank:
			head[u + 2]++;
			break;
		case btrc_win_rx_jump:
			if (in.target >= lo && in.target <= hi) head[in.target - lo + 1]++;
			break;
		case btrc_win_rx_split:
			head[u + 2]++;
			if (in.target >= lo && in.target <= hi) head[in.target - lo + 1]++;
			break;
		default: break;
		}
	}
	for (int v = 1; v <= m; ++v) head[v] += head[v - 1];
	for (int u = 0; u < m - 1; ++u) {
		btrc_win_rx_inst in = rx->code[lo + u];
		switch (in.op) {
		case btrc_win_rx_assert:
		case btrc_win_rx_open:
		case btrc_win_rx_close:
		case btrc_win_rx_mark:
		case btrc_win_rx_rank:
			from[head[u + 1]++] = u;
			break;
		case btrc_win_rx_jump:
			if (in.target >= lo && in.target <= hi) from[head[in.target - lo]++] = u;
			break;
		case btrc_win_rx_split:
			from[head[u + 1]++] = u;
			if (in.target >= lo && in.target <= hi) from[head[in.target - lo]++] = u;
			break;
		default: break;
		}
	}
	/* Shift head back so head[v] .. head[v + 1] bounds v's incoming edges. */
	for (int v = m; v > 0; --v) head[v] = head[v - 1];
	head[0] = 0;

	int *queue = ctx->queue;
	for (size_t off = rows; off-- > 0;) {
		regoff_t pos = i + (regoff_t)off;
		int qhead = 0, qtail = 0;
		if (off == rows - 1) {
			btrc_win_rx_bit_set(bits, off, width - 1, width);
			queue[qtail++] = m - 1;
		} else {
			unsigned char byte = ctx->s[pos];
			for (int u = 0; u < m - 1; ++u) {
				btrc_win_rx_inst in = rx->code[lo + u];
				if (in.op == btrc_win_rx_byte &&
				    btrc_win_rx_bit_get(bits, off + 1, (size_t)(u + 1), width) &&
				    btrc_win_set_has(&rx->nodes[in.arg].bytes, byte)) {
					btrc_win_rx_bit_set(bits, off, (size_t)u, width);
					queue[qtail++] = u;
				}
			}
		}
		while (qhead < qtail) {
			int v = queue[qhead++];
			for (int e = head[v]; e < head[v + 1]; ++e) {
				int u = from[e];
				if (btrc_win_rx_bit_get(bits, off, (size_t)u, width)) continue;
				btrc_win_rx_inst in = rx->code[lo + u];
				if (in.op == btrc_win_rx_assert &&
				    !btrc_win_rx_boundary_ok(in.arg, ctx->s, pos, rx->flags, ctx->eflags))
					continue;
				btrc_win_rx_bit_set(bits, off, (size_t)u, width);
				queue[qtail++] = u;
			}
		}
	}
	*out_bits = bits;
	return 0;
}

static inline regoff_t btrc_win_rx_forward_max(btrc_win_rx_extract_ctx *ctx, int lo, int hi, regoff_t cur, regoff_t j,
                                               int require_nonempty, const unsigned char *bits,
                                               int ext_lo, size_t ext_w, regoff_t ext_i)
{
	if (lo == hi) {
		if (require_nonempty) return -1;
		return btrc_win_rx_bit_get(bits, (size_t)(cur - ext_i), (size_t)(hi - ext_lo), ext_w) ? cur : -1;
	}
	const btrc_win_rx_program *rx = ctx->rx;
	int *now = ctx->now_list, *next = ctx->next_list, *queue = ctx->queue;
	int now_count = 0;
	if (btrc_win_rx_bit_get(bits, (size_t)(cur - ext_i), (size_t)(lo - ext_lo), ext_w)) now[now_count++] = lo;
	regoff_t best_k = -1;
	for (regoff_t pos = cur; pos <= j && now_count > 0; ++pos) {
		size_t row = (size_t)(pos - ext_i);
		unsigned int g = btrc_win_rx_next_gen(ctx, hi - lo + 1);
		int qhead = 0, qtail = 0;
		for (int k = 0; k < now_count; ++k) {
			int pc = now[k];
			if (ctx->seen[pc - lo] != g) {
				ctx->seen[pc - lo] = g;
				queue[qtail++] = pc;
			}
		}
		while (qhead < qtail) {
			int pc = queue[qhead++];
			if (pc == hi) {
				if (!require_nonempty || pos > cur) best_k = pos;
				continue;
			}
			btrc_win_rx_inst in = rx->code[pc];
			int d1 = -1, d2 = -1;
			switch (in.op) {
			case btrc_win_rx_byte: continue;
			case btrc_win_rx_assert:
				if (!btrc_win_rx_boundary_ok(in.arg, ctx->s, pos, rx->flags, ctx->eflags)) continue;
				d1 = pc + 1;
				break;
			case btrc_win_rx_split: d1 = pc + 1; d2 = in.target; break;
			case btrc_win_rx_jump: d1 = in.target; break;
			case btrc_win_rx_open:
			case btrc_win_rx_close:
			case btrc_win_rx_mark:
			case btrc_win_rx_rank: d1 = pc + 1; break;
			default: continue;
			}
			if (d1 >= lo && d1 <= hi && ctx->seen[d1 - lo] != g &&
			    btrc_win_rx_bit_get(bits, row, (size_t)(d1 - ext_lo), ext_w)) {
				ctx->seen[d1 - lo] = g;
				queue[qtail++] = d1;
			}
			if (d2 >= lo && d2 <= hi && ctx->seen[d2 - lo] != g &&
			    btrc_win_rx_bit_get(bits, row, (size_t)(d2 - ext_lo), ext_w)) {
				ctx->seen[d2 - lo] = g;
				queue[qtail++] = d2;
			}
		}
		if (pos == j) break;
		int next_count = 0;
		unsigned int ng = btrc_win_rx_next_gen(ctx, hi - lo + 1);
		unsigned char byte = ctx->s[pos];
		size_t next_row = (size_t)(pos + 1 - ext_i);
		for (int k = 0; k < qtail; ++k) {
			int pc = queue[k];
			if (pc >= hi) continue;
			btrc_win_rx_inst in = rx->code[pc];
			if (in.op == btrc_win_rx_byte && btrc_win_set_has(&rx->nodes[in.arg].bytes, byte)) {
				int dst = pc + 1;
				if (dst <= hi && ctx->seen[dst - lo] != ng &&
				    btrc_win_rx_bit_get(bits, next_row, (size_t)(dst - ext_lo), ext_w)) {
					ctx->seen[dst - lo] = ng;
					next[next_count++] = dst;
				}
			}
		}
		int *swap = now;
		now = next;
		next = swap;
		now_count = next_count;
	}
	return best_k;
}

static inline int btrc_win_rx_is_zero_width_noop(const btrc_win_rx_node *node)
{
	return node->op == btrc_win_rx_assert || (node->op == btrc_win_rx_repeat && node->max == 0);
}

static inline int btrc_win_rx_extract_node(btrc_win_rx_extract_ctx *ctx, int n, regoff_t i, regoff_t j);

static inline int btrc_win_rx_extract_seq(btrc_win_rx_extract_ctx *ctx, int first, regoff_t i, regoff_t j)
{
	const btrc_win_rx_node *nodes = ctx->rx->nodes;
	while (first && btrc_win_rx_is_zero_width_noop(&nodes[first])) first = nodes[first].next;
	if (!first || !nodes[first].seq_has_group) return 0;
	int tail = first;
	for (int n = first; n; n = nodes[n].next) {
		if (!btrc_win_rx_is_zero_width_noop(&nodes[n])) tail = n;
	}
	int stop = nodes[tail].next;
	if (nodes[first].next == stop) return btrc_win_rx_extract_node(ctx, first, i, j);

	int seq_lo = nodes[first].entry;
	int seq_hi = nodes[tail].exit;
	size_t width = (size_t)(seq_hi - seq_lo + 1);
	unsigned char *bits = NULL;
	int err = btrc_win_rx_backward(ctx, seq_lo, seq_hi, i, j, &bits);
	if (err) return err;

	int task_cap = 0, task_count = 0;
	for (int n = first; n != stop; n = nodes[n].next) {
		if (!nodes[n].seq_has_group) break;
		if (nodes[n].has_group) ++task_cap;
	}
	btrc_win_rx_span_task stack_tasks[16];
	btrc_win_rx_span_task *tasks = task_cap <= 16
	    ? stack_tasks
	    : (btrc_win_rx_span_task *)malloc((size_t)task_cap * sizeof *tasks);
	if (!tasks) {
		free(bits);
		return REG_ESPACE;
	}
	regoff_t cur = i;
	for (int n = first; n != stop; n = nodes[n].next) {
		if (!nodes[n].seq_has_group) break;
		regoff_t k;
		if (nodes[n].next == stop) {
			k = j;
		} else {
			k = btrc_win_rx_forward_max(ctx, nodes[n].entry, nodes[n].exit, cur, j, 0,
			                            bits, seq_lo, width, i);
			if (k < 0) {
				err = REG_BADPAT;
				break;
			}
		}
		if (nodes[n].has_group) tasks[task_count++] = (btrc_win_rx_span_task){n, cur, k};
		cur = k;
	}
	free(bits);
	for (int t = 0; !err && t < task_count; ++t)
		err = btrc_win_rx_extract_node(ctx, tasks[t].node, tasks[t].start, tasks[t].end);
	if (tasks != stack_tasks) free(tasks);
	return err;
}

static inline int btrc_win_rx_extract_node(btrc_win_rx_extract_ctx *ctx, int n, regoff_t i, regoff_t j)
{
	const btrc_win_rx_node *nodes = ctx->rx->nodes;
	const btrc_win_rx_node *node = &nodes[n];
	if (!node->has_group) return 0;
	if (node->op == btrc_win_rx_group) {
		for (int g = node->arg; g <= node->max; ++g) ctx->groups[g] = (regmatch_t){-1, -1};
		ctx->groups[node->arg] = (regmatch_t){i, j};
		return btrc_win_rx_extract_seq(ctx, node->child, i, j);
	}
	if (node->op == btrc_win_rx_choice) {
		for (int arm = n; arm; arm = nodes[arm].arg) {
			if (btrc_win_rx_slice_matches(ctx, nodes[arm].arm_entry, nodes[arm].arm_exit, i, j))
				return btrc_win_rx_extract_seq(ctx, nodes[arm].child, i, j);
		}
		return REG_BADPAT;
	}
	if (node->op == btrc_win_rx_repeat) {
		if (node->max == 0) return 0;
		int child = node->child;
		int width_child = nodes[child].exit - nodes[child].entry;
		int rep_lo = node->entry, rep_hi = node->exit;
		size_t width = (size_t)(rep_hi - rep_lo + 1);
		unsigned char *bits = NULL;
		int err = btrc_win_rx_backward(ctx, rep_lo, rep_hi, i, j, &bits);
		if (err) return err;

		int only_last = nodes[child].op == btrc_win_rx_group;
		btrc_win_rx_span_task *iters = NULL;
		int iter_count = 0, iter_cap = 0;
		regoff_t last_s = -1, last_e = -1;
		regoff_t cur = i;

		for (int c = 0; !err && c < node->min; ++c) {
			int c_lo = rep_lo + c * width_child;
			int c_hi = c_lo + width_child;
			regoff_t k = (c == node->min - 1 && node->max == node->min)
			    ? j
			    : btrc_win_rx_forward_max(ctx, c_lo, c_hi, cur, j, 0, bits, rep_lo, width, i);
			if (k < 0) {
				err = REG_BADPAT;
				break;
			}
			if (only_last) {
				last_s = cur;
				last_e = k;
			} else {
				if (iter_count == iter_cap) {
					int ncap = iter_cap ? iter_cap * 2 : 16;
					btrc_win_rx_span_task *next_it = (btrc_win_rx_span_task *)realloc(
					    iters, (size_t)ncap * sizeof *next_it);
					if (!next_it) { err = REG_ESPACE; break; }
					iters = next_it;
					iter_cap = ncap;
				}
				iters[iter_count++] = (btrc_win_rx_span_task){child, cur, k};
			}
			cur = k;
		}
		if (!err && node->max > node->min) {
			for (int c = node->min; !err && c < node->max; ++c) {
				int c_lo = rep_lo + node->min * width_child + (c - node->min) * (width_child + 1) + 1;
				int c_hi = c_lo + width_child;
				if (cur == j) {
					if (node->min == 0 && c == 0 && btrc_win_rx_slice_matches(ctx, c_lo, c_hi, j, j)) {
						if (only_last) { last_s = j; last_e = j; }
						else {
							if (iter_count == iter_cap) {
								int ncap = iter_cap ? iter_cap * 2 : 16;
								btrc_win_rx_span_task *next_it = (btrc_win_rx_span_task *)realloc(
								    iters, (size_t)ncap * sizeof *next_it);
								if (!next_it) { err = REG_ESPACE; break; }
								iters = next_it;
								iter_cap = ncap;
							}
							iters[iter_count++] = (btrc_win_rx_span_task){child, j, j};
						}
					}
					break;
				}
				regoff_t k = btrc_win_rx_forward_max(ctx, c_lo, c_hi, cur, j, 1, bits, rep_lo, width, i);
				if (k <= cur) break;
				if (only_last) {
					last_s = cur;
					last_e = k;
				} else {
					if (iter_count == iter_cap) {
						int ncap = iter_cap ? iter_cap * 2 : 16;
						btrc_win_rx_span_task *next_it = (btrc_win_rx_span_task *)realloc(
						    iters, (size_t)ncap * sizeof *next_it);
						if (!next_it) { err = REG_ESPACE; break; }
						iters = next_it;
						iter_cap = ncap;
					}
					iters[iter_count++] = (btrc_win_rx_span_task){child, cur, k};
				}
				cur = k;
			}
		} else if (!err && node->max < 0) {
			int loop_head = rep_lo + node->min * width_child;
			int b_lo = loop_head + 1;
			int b_hi = b_lo + width_child;
			if (node->min == 0 && cur == j) {
				if (btrc_win_rx_slice_matches(ctx, b_lo, b_hi, j, j)) {
					if (only_last) { last_s = j; last_e = j; }
					else {
						iters = (btrc_win_rx_span_task *)malloc(sizeof *iters);
						if (!iters) err = REG_ESPACE;
						else iters[iter_count++] = (btrc_win_rx_span_task){child, j, j};
					}
				}
			}
			while (!err && cur < j) {
				regoff_t k = btrc_win_rx_forward_max(ctx, b_lo, b_hi, cur, j, 1, bits, rep_lo, width, i);
				if (k <= cur) break;
				if (only_last) {
					last_s = cur;
					last_e = k;
				} else {
					if (iter_count == iter_cap) {
						int ncap = iter_cap ? iter_cap * 2 : 16;
						btrc_win_rx_span_task *next_it = (btrc_win_rx_span_task *)realloc(
						    iters, (size_t)ncap * sizeof *next_it);
						if (!next_it) { err = REG_ESPACE; break; }
						iters = next_it;
						iter_cap = ncap;
					}
					iters[iter_count++] = (btrc_win_rx_span_task){child, cur, k};
				}
				cur = k;
			}
		}
		free(bits);
		if (!err) {
			if (only_last) {
				if (last_s >= 0) err = btrc_win_rx_extract_node(ctx, child, last_s, last_e);
			} else {
				for (int t = 0; !err && t < iter_count; ++t)
					err = btrc_win_rx_extract_node(ctx, child, iters[t].start, iters[t].end);
			}
		}
		free(iters);
		return err;
	}
	return 0;
}

static inline int btrc_win_rx_extract_submatches(const btrc_win_rx_program *rx, const unsigned char *s, int eflags,
                                                 regoff_t first, regoff_t last, size_t nmatch, regmatch_t *matches)
{
	int m = rx->code_count;
	regmatch_t *groups = (regmatch_t *)malloc(((size_t)rx->capture_count + 1u) * sizeof *groups);
	int *rev_head = (int *)malloc(((size_t)m + 1u) * sizeof *rev_head);
	int *rev_from = (int *)malloc(2u * (size_t)m * sizeof *rev_from);
	int *queue = (int *)malloc((size_t)m * sizeof *queue);
	int *now_list = (int *)malloc((size_t)m * sizeof *now_list);
	int *next_list = (int *)malloc((size_t)m * sizeof *next_list);
	unsigned int *seen = (unsigned int *)calloc((size_t)m, sizeof *seen);
	int err = (!groups || !rev_head || !rev_from || !queue || !now_list || !next_list || !seen) ? REG_ESPACE : 0;
	if (!err) {
		groups[0] = (regmatch_t){first, last};
		for (int g = 1; g <= rx->capture_count; ++g) groups[g] = (regmatch_t){-1, -1};
		btrc_win_rx_extract_ctx ctx = {rx, s, eflags, groups, rev_head, rev_from, queue, now_list, next_list, seen, 0};
		err = btrc_win_rx_extract_seq(&ctx, rx->root, first, last);
		if (!err) {
			for (size_t g = 0; g < nmatch; ++g)
				matches[g] = g <= (size_t)rx->capture_count ? groups[g] : (regmatch_t){-1, -1};
		}
	}
	free(seen);
	free(next_list);
	free(now_list);
	free(queue);
	free(rev_from);
	free(rev_head);
	free(groups);
	return err;
}

/* ── Pass 3: Bounded tagged NFA (BRE backreferences & large-span fallback) ─ */

typedef struct {
	int pc, sibling, queue;
	regoff_t start, progress;
} btrc_win_rx_state;

typedef struct {
	int count, capacity, head, tail, tags;
	unsigned int work;
	int *at;
	btrc_win_rx_state *states;
	regoff_t *spans;
} btrc_win_rx_frontier;

static inline void btrc_win_rx_retire(btrc_win_rx_frontier *f)
{
	for (int i = 0; i < f->count; ++i) f->at[f->states[i].pc] = -1;
	f->count = 0;
	f->head = f->tail = -1;
}

static inline void btrc_win_rx_destroy(btrc_win_rx_frontier *f)
{
	free(f->at);
	free(f->states);
	free(f->spans);
}

static inline int btrc_win_rx_init(btrc_win_rx_frontier *f, const btrc_win_rx_program *rx, int tags)
{
	f->tags = tags;
	f->at = (int *)malloc((size_t)rx->code_count * sizeof *f->at);
	if (!f->at) return REG_ESPACE;
	for (int i = 0; i < rx->code_count; ++i) f->at[i] = -1;
	f->tail = f->head = -1;
	return 0;
}

static inline regoff_t *btrc_win_rx_spans(const btrc_win_rx_frontier *f, int index)
{
	return f->tags ? f->spans + (size_t)index * (size_t)f->tags : NULL;
}

static inline int btrc_win_rx_better(const btrc_win_rx_program *rx, int tags,
                                     const regoff_t *candidate, const regoff_t *existing)
{
	for (int t = 0; t < tags; ++t) {
		if (candidate[t] == existing[t]) continue;
		if (candidate[t] < 0) return 0;
		if (existing[t] < 0) return 1;
		return rx->maximize[t] ? candidate[t] > existing[t] : candidate[t] < existing[t];
	}
	return 0;
}

static inline int btrc_win_rx_same_history(const btrc_win_rx_program *rx, const regoff_t *a, const regoff_t *b)
{
	for (int g = 1; (rx->references >> g) != 0; ++g) {
		if (!(rx->references & (1 << g))) continue;
		int t = rx->group_tags[g];
		if (a[t] != b[t] || a[t + 1] != b[t + 1]) return 0;
	}
	return 1;
}

static inline int btrc_win_rx_add(btrc_win_rx_frontier *f, const btrc_win_rx_program *rx, int pc,
                                  regoff_t start, regoff_t progress, const regoff_t *spans,
                                  unsigned int *total_work)
{
	if (!f->work || !*total_work) return REG_ESPACE;
	--f->work;
	--(*total_work);
	int i = f->at[pc];
	for (; i >= 0; i = f->states[i].sibling) {
		if (!f->work || !*total_work) return REG_ESPACE;
		--f->work;
		--(*total_work);
		btrc_win_rx_state *old = &f->states[i];
		if (old->progress != progress || !btrc_win_rx_same_history(rx, spans, btrc_win_rx_spans(f, i))) continue;
		if (old->start < start || (old->start == start &&
		    !btrc_win_rx_better(rx, f->tags, spans, btrc_win_rx_spans(f, i)))) return 0;
		break;
	}
	if (i < 0) {
		if (f->count == f->capacity) {
			size_t row = sizeof *f->states + (size_t)f->tags * sizeof *spans;
			size_t limit = (size_t)btrc_win_rx_frontier_limit / row;
			int cap = f->capacity ? 2 * f->capacity : 8;
			if ((size_t)cap > limit) cap = (int)limit;
			if (cap <= f->capacity) return REG_ESPACE;
			btrc_win_rx_state *states = (btrc_win_rx_state *)realloc(f->states, (size_t)cap * sizeof *states);
			if (!states) return REG_ESPACE;
			f->states = states;
			if (f->tags) {
				regoff_t *data = (regoff_t *)realloc(f->spans, (size_t)cap * (size_t)f->tags * sizeof *data);
				if (!data) return REG_ESPACE;
				f->spans = data;
			}
			f->capacity = cap;
		}
		i = f->count++;
		f->states[i] = (btrc_win_rx_state){pc, f->at[pc], -2, start, progress};
		f->at[pc] = i;
	}
	f->states[i].start = start;
	if (f->tags) memcpy(btrc_win_rx_spans(f, i), spans, (size_t)f->tags * sizeof *spans);
	if (f->states[i].queue == -2) {
		if (f->tail >= 0) f->states[f->tail].queue = i;
		else f->head = i;
		f->tail = i;
		f->states[i].queue = -1;
	}
	return 0;
}

static inline int btrc_win_rx_exec_tagged(const btrc_win_rx_program *rx, const unsigned char *s, size_t nmatch,
                                          regmatch_t *matches, int eflags)
{
	int tags = rx->tag_count;
	btrc_win_rx_frontier rows[2] = {{0}, {0}};
	btrc_win_rx_frontier *now = &rows[0], *next = &rows[1];
	int error = btrc_win_rx_init(now, rx, tags);
	if (!error) error = btrc_win_rx_init(next, rx, tags);
	regoff_t *scratch = tags ? (regoff_t *)malloc((size_t)tags * 2u * sizeof *scratch) : NULL;
	if (tags && !scratch) error = REG_ESPACE;
	regoff_t *best = tags && scratch ? scratch + tags : NULL;
	regoff_t first = -1, last = -1;
	unsigned int total_work = btrc_win_rx_total_work;
	for (regoff_t pos = 0; !error; ++pos) {
		now->work = next->work = 65536u + 128u * (unsigned int)rx->code_count;
		if (first < 0) {
			for (int t = 0; t < tags; ++t) scratch[t] = -1;
			error = btrc_win_rx_add(now, rx, 0, pos, 0, scratch, &total_work);
		}
		while (!error && now->head >= 0) {
			int i = now->head;
			btrc_win_rx_state st = now->states[i];
			now->head = st.queue;
			if (now->head < 0) now->tail = -1;
			now->states[i].queue = -2;
			if (first >= 0 && st.start > first) continue;
			if (tags) memcpy(scratch, btrc_win_rx_spans(now, i), (size_t)tags * sizeof *scratch);
			btrc_win_rx_inst in = rx->code[st.pc];
			int dest = st.pc + 1;
			switch (in.op) {
			case btrc_win_rx_byte:
				continue;
			case btrc_win_rx_ref: {
				int t = rx->group_tags[in.arg];
				if (scratch[t] < 0 || scratch[t + 1] < 0) continue;
				if (scratch[t + 1] != scratch[t]) continue;
				break;
			}
			case btrc_win_rx_assert:
				if (!btrc_win_rx_boundary_ok(in.arg, s, pos, rx->flags, eflags)) continue;
				break;
			case btrc_win_rx_split:
				error = btrc_win_rx_add(now, rx, in.target, st.start, 0, scratch, &total_work);
				break;
			case btrc_win_rx_jump:
				dest = in.target;
				break;
			case btrc_win_rx_open:
				if (tags) {
					for (int g = in.arg; g <= in.target; ++g) {
						int t = rx->group_tags[g];
						scratch[t] = scratch[t + 1] = -1;
					}
					scratch[rx->group_tags[in.arg]] = pos;
				}
				break;
			case btrc_win_rx_close:
				if (tags) scratch[rx->group_tags[in.arg] + 1] = pos;
				break;
			case btrc_win_rx_rank:
				if (tags) scratch[in.arg] = in.target;
				break;
			case btrc_win_rx_mark:
				if (tags) scratch[in.arg] = pos;
				break;
			case btrc_win_rx_accept:
				if (first < 0 || st.start < first || (st.start == first && (pos > last ||
				    (pos == last && btrc_win_rx_better(rx, tags, scratch, best))))) {
					first = st.start;
					last = pos;
					if (tags) memcpy(best, scratch, (size_t)tags * sizeof *best);
				}
				continue;
			default:
				error = REG_BADPAT;
				break;
			}
			if (!error) error = btrc_win_rx_add(now, rx, dest, st.start, 0, scratch, &total_work);
		}
		if (error || !s[pos] || (first >= 0 && !nmatch)) break;
		for (int i = 0; !error && i < now->count; ++i) {
			btrc_win_rx_state st = now->states[i];
			if (first >= 0 && st.start > first) continue;
			btrc_win_rx_inst in = rx->code[st.pc];
			const regoff_t *spans = btrc_win_rx_spans(now, i);
			int dest = st.pc + 1;
			regoff_t progress = 0;
			if (in.op == btrc_win_rx_byte) {
				if (!btrc_win_set_has(&rx->nodes[in.arg].bytes, s[pos])) continue;
			} else if (in.op == btrc_win_rx_ref) {
				int t = rx->group_tags[in.arg];
				if (spans[t] < 0 || spans[t + 1] < 0) continue;
				regoff_t len = spans[t + 1] - spans[t];
				if (st.progress >= len) continue;
				unsigned char captured = s[spans[t] + st.progress];
				unsigned char cur = s[pos];
				if ((rx->flags & REG_ICASE) ? (btrc_win_fold(captured) != btrc_win_fold(cur)) : (captured != cur))
					continue;
				if (st.progress + 1 < len) {
					dest = st.pc;
					progress = st.progress + 1;
				}
			} else {
				continue;
			}
			error = btrc_win_rx_add(next, rx, dest, st.start, progress, spans, &total_work);
		}
		if (first >= 0 && !next->count) break;
		btrc_win_rx_retire(now);
		btrc_win_rx_frontier *swap = now;
		now = next;
		next = swap;
	}
	if (!error && first < 0) error = REG_NOMATCH;
	if (!error && nmatch) {
		matches[0] = (regmatch_t){first, last};
		for (size_t g = 1; g < nmatch; ++g) {
			if (g <= (size_t)rx->capture_count) {
				int t = rx->group_tags[g];
				matches[g] = (regmatch_t){best[t], best[t + 1]};
			} else {
				matches[g] = (regmatch_t){-1, -1};
			}
		}
	}
	free(scratch);
	btrc_win_rx_destroy(now);
	btrc_win_rx_destroy(next);
	return error;
}

static inline int btrc_win_rx_exec(const btrc_win_rx_program *rx, const char *text, size_t nmatch,
                                   regmatch_t *matches, int eflags)
{
	if (!rx || !text) return REG_BADPAT;
	if (rx->flags & REG_NOSUB) nmatch = 0;
	const unsigned char *s = (const unsigned char *)text;
	if (rx->references) return btrc_win_rx_exec_tagged(rx, s, nmatch, matches, eflags);

	regoff_t first = -1, last = -1;
	int status = btrc_win_rx_find_span(rx, s, eflags, nmatch > 0, &first, &last);
	if (status) return status;
	if (!nmatch) return 0;
	if (nmatch == 1 || rx->capture_count == 0) {
		matches[0] = (regmatch_t){first, last};
		for (size_t g = 1; g < nmatch; ++g) matches[g] = (regmatch_t){-1, -1};
		return 0;
	}
	status = btrc_win_rx_extract_submatches(rx, s, eflags, first, last, nmatch, matches);
	if (status == REG_ESPACE) return btrc_win_rx_exec_tagged(rx, s, nmatch, matches, eflags);
	return status;
}
