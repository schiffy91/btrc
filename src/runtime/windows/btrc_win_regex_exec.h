/* Simulate the Thompson program one subject byte at a time. Epsilon edges
   are closed before any consuming edge is taken. At a fixed (pc, offset)
   only the best leftmost path survives. A BRE backreference also depends
   on the referenced capture spans and on progress through that reference;
   those are part of the state key. */
#pragma once

typedef struct {
	int pc, sibling, queue;
	regoff_t start, progress;
} btrc_win_rx_state;

typedef struct {
	int count, capacity, head, tail, tags;
	unsigned int work;
	regoff_t position;
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
	/* A later backreference consumed the reported capture. Two histories
	   can accept at the same offset after consuming different intervals. */
	for (int g = 1; (rx->references >> g) != 0; ++g) {
		if (!(rx->references & (1 << g))) continue;
		int t = rx->group_tags[g];
		regoff_t length = candidate[t] < 0 || candidate[t + 1] < 0 ? -1 : candidate[t + 1] - candidate[t];
		regoff_t previous = existing[t] < 0 || existing[t + 1] < 0 ? -1 : existing[t + 1] - existing[t];
		if (length != previous) return length > previous;
		if (length == 0 && candidate[t] != existing[t]) return candidate[t] < existing[t];
	}
	for (int t = 0; t < tags; ++t) {
		if (rx->maximize[t] >= 2 || candidate[t] == existing[t]) continue;
		if (candidate[t] < 0) return 0;
		if (existing[t] < 0) return 1;
		return rx->maximize[t] ? candidate[t] > existing[t] : candidate[t] < existing[t];
	}
	return 0;
}

static inline int btrc_win_rx_same_history(const btrc_win_rx_program *rx, const regoff_t *a, const regoff_t *b, regoff_t pos)
{
	for (int i = 0; i < rx->guard_count; ++i) {
		int t = rx->guard_tags[i];
		if ((a[t] == pos) != (b[t] == pos)) return 0;
	}
	for (int g = 1; (rx->references >> g) != 0; ++g) {
		if (!(rx->references & (1 << g))) continue;
		int t = rx->group_tags[g];
		if (a[t] != b[t] || a[t + 1] != b[t + 1]) return 0;
	}
	return 1;
}

static inline int btrc_win_rx_add(btrc_win_rx_frontier *f, const btrc_win_rx_program *rx, int pc,
                                  regoff_t start, regoff_t progress, const regoff_t *spans)
{
	/* In particular, nine BRE backreferences can distinguish many capture
	   histories. Charge each lookup/comparison against the per-byte budget. */
	if (!f->work) return REG_ESPACE;
	--f->work;
	int i = f->at[pc];
	for (; i >= 0; i = f->states[i].sibling) {
		if (!f->work) return REG_ESPACE;
		--f->work;
		btrc_win_rx_state *old = &f->states[i];
		if (old->progress != progress || !btrc_win_rx_same_history(rx, spans, btrc_win_rx_spans(f, i), f->position)) continue;
		if (old->start < start || (old->start == start &&
		    !btrc_win_rx_better(rx, f->tags, spans, btrc_win_rx_spans(f, i)))) return 0;
		break;
	}
	if (i < 0) {
		if (f->count == f->capacity) {
			size_t row = sizeof *f->states + (size_t)f->tags * sizeof *spans;
			size_t limit = (32u * 1024u * 1024u) / row;
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
	case btrc_win_rx_word_boundary: return !pos || !c || word != previous;
	default: return pos && c && word == previous;
	}
}

static inline int btrc_win_regexec(const regex_t *restrict re, const char *restrict text, size_t nmatch,
                                   regmatch_t *restrict matches, int flags)
{
	const btrc_win_rx_program *rx = (const btrc_win_rx_program *)re->__opaque;
	if (!rx) return REG_BADPAT;
	if (rx->flags & REG_NOSUB) nmatch = 0;
	int tags = ((nmatch > 1 && re->re_nsub) || rx->references || rx->guard_count) ? rx->tag_count : 0;
	btrc_win_rx_frontier rows[2] = {{0}, {0}};
	btrc_win_rx_frontier *now = &rows[0], *next = &rows[1];
	int error = btrc_win_rx_init(now, rx, tags);
	if (!error) error = btrc_win_rx_init(next, rx, tags);
	regoff_t *scratch = tags ? (regoff_t *)malloc((size_t)tags * 2 * sizeof *scratch) : NULL;
	if (tags && !scratch) error = REG_ESPACE;
	regoff_t *best = tags && scratch ? scratch + tags : NULL;
	regoff_t first = -1, last = -1;
	const unsigned char *s = (const unsigned char *)text;
	for (regoff_t pos = 0; !error; ++pos) {
		now->position = pos;
		next->position = pos + (s[pos] != 0);
		now->work = next->work = 65536u + 128u * (unsigned int)rx->code_count;
		if (first < 0) {
			for (int t = 0; t < tags; ++t) scratch[t] = -1;
			error = btrc_win_rx_add(now, rx, 0, pos, 0, scratch);
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
				if (scratch[t] < 0) {
					if (!in.target) continue;
				} else if ((scratch[t + 1] < 0 ? pos : scratch[t + 1]) != scratch[t]) continue;
				break;
			}
			case btrc_win_rx_assert:
				if (!btrc_win_rx_boundary_ok(in.arg, s, pos, rx->flags, flags)) continue;
				break;
			case btrc_win_rx_split:
				error = btrc_win_rx_add(now, rx, in.target, st.start, 0, scratch);
				break;
			case btrc_win_rx_jump: dest = in.target; break;
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
			case btrc_win_rx_progress:
				if (scratch[in.arg] == pos) continue;
				scratch[in.arg] = -1;
				break;
			case btrc_win_rx_at_exit:
				for (int g = in.arg; tags && g <= in.target; ++g) {
					int t = rx->group_tags[g];
					if (scratch[t] < 0) scratch[t] = scratch[t + 1] = pos;
				}
				break;
			case btrc_win_rx_nonempty:
				if (tags && scratch[rx->group_tags[in.arg]] == pos) continue;
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
			default: error = REG_BADPAT; break;
			}
			if (!error) error = btrc_win_rx_add(now, rx, dest, st.start, 0, scratch);
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
				regoff_t end = spans[t + 1] < 0 ? pos - st.progress : spans[t + 1];
				if (spans[t] < 0 || st.progress >= end - spans[t]) continue;
				/* Windows folds pattern literals with REG_ICASE, but its BRE
				   backreferences compare the bytes of the captured text. */
				if (s[spans[t] + st.progress] != s[pos]) continue;
				if (st.progress + 1 < end - spans[t]) { dest = st.pc; progress = st.progress + 1; }
			} else continue;
			error = btrc_win_rx_add(next, rx, dest, st.start, progress, spans);
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
			if (g <= re->re_nsub) {
				int t = rx->group_tags[g];
				if (rx->maximize[t] == 3) matches[g] = (regmatch_t){first, first};
				else matches[g] = (regmatch_t){best[t], best[t + 1]};
			} else matches[g] = (regmatch_t){-1, -1};
		}
	}
	free(scratch);
	btrc_win_rx_destroy(now);
	btrc_win_rx_destroy(next);
	return error;
}
