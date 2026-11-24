/* A position automaton for grouped Windows EREs. Counted repetitions
   inside another repetition can share consuming positions with their suffix,
   which changes the byte language of the historical Windows provider. */
#pragma once
#include "btrc_win_regex_compile.h"
#include "btrc_win_regex_block.h"
#include "btrc_win_regex_suffix.h"
#include "btrc_win_regex_boundary_blocks.h"

enum { btrc_win_pos_limit = 127, btrc_win_pos_nodes = 512 };
typedef struct { uint64_t low, high; } btrc_win_pos_bits;

static inline btrc_win_pos_bits btrc_win_pos_bit(int index)
{
	uint64_t bit = UINT64_C(1) << (index % 64);
	return index < 64 ? (btrc_win_pos_bits){bit, 0} : (btrc_win_pos_bits){0, bit};
}

static inline int btrc_win_pos_contains(btrc_win_pos_bits bits, int index)
{
	return (int)(((index < 64 ? bits.low : bits.high) >> (index % 64)) & 1);
}

static inline btrc_win_pos_bits btrc_win_pos_union_bits(btrc_win_pos_bits a, btrc_win_pos_bits b)
{
	return (btrc_win_pos_bits){a.low | b.low, a.high | b.high};
}

static inline int btrc_win_pos_any(btrc_win_pos_bits bits) { return (bits.low | bits.high) != 0; }

typedef struct {
	int source;
	btrc_win_pos_bits target;
	btrc_win_byte_set bytes;
} btrc_win_pos_edge;

typedef struct {
	btrc_win_group_header header;
	btrc_win_rx_blocks ranked_blocks;
	btrc_win_suffix_span optional_suffix;
	btrc_win_boundary_blocks boundary_blocks;
	btrc_win_pos_bits initial;
	/* When one source assertion is present, these are its initial positions
	   and outgoing transitions at a byte boundary where it holds. */
	btrc_win_pos_bits *when_true;
	int edges, nullable, assertion;
	btrc_win_pos_edge edge[];
} btrc_win_pos_program;

enum btrc_win_pos_op { btrc_win_pos_empty, btrc_win_pos_byte, btrc_win_pos_boundary, btrc_win_pos_cat,
                       btrc_win_pos_union, btrc_win_pos_optional, btrc_win_pos_star, btrc_win_pos_plus };
typedef struct {
	enum btrc_win_pos_op op;
	int left, right, width, requires_byte, has_boundary;
} btrc_win_pos_node;

typedef struct {
	btrc_win_rx_parser *parser;
	btrc_win_pos_program *program;
	btrc_win_pos_node nodes[btrc_win_pos_nodes];
	int used, extra, failed, conditional, assertion_true;
	int positions[btrc_win_pos_limit], position_count;
} btrc_win_pos_builder;

/* Until building finishes, a byte leaf names its source syntax node and
   its consuming position. A composite names its children and counts the
   byte leaves a repeated copy would contain. Index zero denotes epsilon. */
static inline int btrc_win_pos_new(btrc_win_pos_builder *b, enum btrc_win_pos_op op, int left, int right)
{
	if (b->failed) return 0;
	if (b->used >= btrc_win_pos_nodes - 1) {
		b->failed = 1;
		return 0;
	}
	btrc_win_pos_node made = { .op = op, .left = left, .right = right };
	if (op == btrc_win_pos_byte) {
		made.width = b->parser->program->nodes[left].copy_stride;
		made.requires_byte = 1;
	} else if (op == btrc_win_pos_boundary) made.has_boundary = 1;
	else {
		const btrc_win_pos_node *a = &b->nodes[left], *z = &b->nodes[right];
		made.width = a->width + z->width;
		made.has_boundary = a->has_boundary || z->has_boundary;
		made.requires_byte = op == btrc_win_pos_cat ? a->requires_byte || z->requires_byte :
		                     op == btrc_win_pos_union ? a->requires_byte && z->requires_byte :
		                     op == btrc_win_pos_plus && a->requires_byte;
		if (!b->conditional && made.has_boundary && ((op == btrc_win_pos_union && !a->requires_byte && !z->requires_byte) ||
		    ((op == btrc_win_pos_optional || op == btrc_win_pos_star) && !a->requires_byte))) b->failed = 1;
	}
	b->nodes[++b->used] = made;
	return b->used;
}

static inline int btrc_win_pos_copy(btrc_win_pos_builder *b, int id, int offset)
{
	if (!id || !offset || b->failed) return id;
	btrc_win_pos_node n = b->nodes[id];
	if (n.op == btrc_win_pos_boundary) return id;
	if (n.op == btrc_win_pos_byte) return btrc_win_pos_new(b, n.op, n.left, n.right + offset);
	int left = btrc_win_pos_copy(b, n.left, offset);
	int right = btrc_win_pos_copy(b, n.right, offset);
	return btrc_win_pos_new(b, n.op, left, right);
}

static inline int btrc_win_pos_sequence(btrc_win_pos_builder *b, int id, int *offset, int depth);

static inline int btrc_win_pos_repeat(btrc_win_pos_builder *b, const btrc_win_rx_node *n, int *offset, int depth)
{
	if (n->max == 0) return 0;
	if (b->parser->program->nodes[n->child].op == btrc_win_rx_repeat) {
		b->failed = 1;
		return 0;
	}
	int counted = n->min > 1 || n->max > 1;
	int inner_offset = counted ? 0 : *offset;
	int child = btrc_win_pos_sequence(b, n->child, &inner_offset, depth + 1);
	if (b->failed) return 0;
	const btrc_win_pos_node *body = &b->nodes[child];
	/* Repeating a zero-width assertion or copying a nullable asserted body
	   inside another repetition requires ranking individual empty paths. */
	if (b->conditional && body->has_boundary &&
	    (!body->width || (counted && depth && !body->requires_byte))) {
		b->failed = 1;
		return 0;
	}
	if (!counted) {
		if (!depth) *offset = b->extra;
		if (n->max == 1 && n->min == 1) return child;
		return btrc_win_pos_new(b, n->max == 1 ? btrc_win_pos_optional :
		                           n->min ? btrc_win_pos_plus : btrc_win_pos_star, child, 0);
	}
	int copies = n->max < 0 ? n->min + 1 : n->max;
	int width = b->nodes[child].width;
	if (!width || copies > 255 / width) { b->failed = 1; return 0; }
	int required = 0, tail = 0;
	for (int i = 0; i < copies && !b->failed; ++i) {
		int copy = btrc_win_pos_copy(b, child, *offset + i * width);
		if (i < n->min) required = required ? btrc_win_pos_new(b, btrc_win_pos_cat, required, copy) : copy;
		else if (n->max < 0) tail = btrc_win_pos_new(b, btrc_win_pos_star, copy, 0);
		else {
			if (tail) copy = btrc_win_pos_new(b, btrc_win_pos_cat, copy, tail);
			/* A counted optional copy prefers skipping the entire copy,
			   even if it contains an asserted empty match of its own. */
			tail = b->conditional ? btrc_win_pos_new(b, btrc_win_pos_union, 0, copy) :
			                        btrc_win_pos_new(b, btrc_win_pos_optional, copy, 0);
		}
	}
	/* The next sibling inside a repetition sees only positions allocated by
	   that child. Outside every repetition it sees all prior expansions. */
	int extra = (copies - 1) * width;
	b->extra += extra;
	*offset = depth ? *offset + extra : b->extra;
	return !required ? tail : !tail ? required : btrc_win_pos_new(b, btrc_win_pos_cat, required, tail);
}

static inline int btrc_win_pos_sequence(btrc_win_pos_builder *b, int id, int *offset, int depth)
{
	btrc_win_rx_node *nodes = b->parser->program->nodes;
	int seq = 0;
	for (; id && !b->failed; id = nodes[id].next) {
		const btrc_win_rx_node *n = &nodes[id];
		int part = 0;
		switch (n->op) {
		case btrc_win_rx_byte:
			part = btrc_win_pos_new(b, btrc_win_pos_byte, id, n->arg + *offset);
			break;
		case btrc_win_rx_assert:
			if (!b->conditional && n->arg != btrc_win_rx_bol && n->arg != btrc_win_rx_eol) b->failed = 1;
			else part = btrc_win_pos_new(b, btrc_win_pos_boundary, n->arg, 0);
			break;
		case btrc_win_rx_group:
			part = btrc_win_pos_sequence(b, n->child, offset, depth);
			break;
		case btrc_win_rx_choice:
			for (int arm = id; arm && !b->failed; arm = nodes[arm].arg) {
				int branch = btrc_win_pos_sequence(b, nodes[arm].child, offset, depth);
				part = arm == id ? branch : btrc_win_pos_new(b, btrc_win_pos_union, part, branch);
			}
			break;
		case btrc_win_rx_repeat:
			part = btrc_win_pos_repeat(b, n, offset, depth);
			break;
		default: b->failed = 1; break;
		}
		if (part) seq = seq ? btrc_win_pos_new(b, btrc_win_pos_cat, seq, part) : part;
	}
	return seq;
}

/* A start anchor after a mandatory byte and an end anchor before one
   can never succeed in the C-locale, non-newline input mode. Retain
   every consuming position on either side so historical aliases still
   reach the same suffixes. Other boundary placements use the fallback. */
static inline int btrc_win_pos_dead_boundaries(const btrc_win_pos_builder *b, int id, int before, int after)
{
	const btrc_win_pos_node *n = &b->nodes[id];
	if (!n->has_boundary) return 1;
	if (n->op == btrc_win_pos_boundary) return n->left == btrc_win_rx_bol ? before : after;
	int cat = n->op == btrc_win_pos_cat;
	return btrc_win_pos_dead_boundaries(b, n->left, before, after || (cat && b->nodes[n->right].requires_byte)) &&
	       btrc_win_pos_dead_boundaries(b, n->right, before || (cat && b->nodes[n->left].requires_byte), after);
}

/* First is a set of consuming positions. Last indexes individual byte
   edges because two occurrences at one position may accept different
   bytes and lead to different suffixes. */
typedef struct { btrc_win_pos_bits first, last; int nullable; } btrc_win_pos_span;

static inline void btrc_win_pos_follow(btrc_win_pos_program *p, btrc_win_pos_bits edges, btrc_win_pos_bits next)
{
	for (int i = 0; i < p->edges; ++i)
		if (btrc_win_pos_contains(edges, i)) p->edge[i].target = btrc_win_pos_union_bits(p->edge[i].target, next);
}

static inline btrc_win_pos_span btrc_win_pos_span_for(btrc_win_pos_builder *b, int id)
{
	btrc_win_pos_span empty = {{0, 0}, {0, 0}, 1};
	if (!id || b->failed) return empty;
	const btrc_win_pos_node *n = &b->nodes[id];
	if (n->op == btrc_win_pos_boundary) return (btrc_win_pos_span){{0, 0}, {0, 0}, b->assertion_true};
	if (n->op == btrc_win_pos_byte) {
		btrc_win_pos_program *p = b->program;
		/* Compact sparse source labels without changing position identity.
		   Equal byte sets at the same position can share their suffixes. */
		int label = 0;
		while (label < b->position_count && b->positions[label] != n->right) ++label;
		if (label == b->position_count) {
			if (label == btrc_win_pos_limit) { b->failed = 1; return empty; }
			b->positions[b->position_count++] = n->right;
		}
		btrc_win_pos_bits position = btrc_win_pos_bit(label);
		const btrc_win_byte_set *bytes = &b->parser->program->nodes[n->left].bytes;
		int slot = 0;
		while (slot < p->edges && (p->edge[slot].source != label ||
		       memcmp(&p->edge[slot].bytes, bytes, sizeof *bytes))) ++slot;
		if (slot == p->edges) {
			if (slot == btrc_win_pos_limit) { b->failed = 1; return empty; }
			p->edge[p->edges++] = (btrc_win_pos_edge){label, {0, 0}, *bytes};
		}
		return (btrc_win_pos_span){position, btrc_win_pos_bit(slot), 0};
	}
	btrc_win_pos_span left = btrc_win_pos_span_for(b, n->left);
	if (n->op == btrc_win_pos_cat || n->op == btrc_win_pos_union) {
		btrc_win_pos_span right = btrc_win_pos_span_for(b, n->right);
		/* Legacy transitions retain the first of adjacent equal destination
		   positions. An asserted path and an ordinary path to that position
		   can differ even when their byte sets coincide. */
		if (b->assertion_true && n->has_boundary && (n->op == btrc_win_pos_union || left.nullable) &&
		    ((left.first.low & right.first.low) || (left.first.high & right.first.high))) b->failed = 1;
		if (n->op == btrc_win_pos_union) {
			/* For an empty match the first structurally nullable arm supplies
			   the assertion; a later arm cannot override its failed boundary. */
			int nullable = left.nullable || right.nullable;
			if (b->conditional) nullable = b->nodes[n->left].requires_byte ? right.nullable : left.nullable;
			return (btrc_win_pos_span){btrc_win_pos_union_bits(left.first, right.first),
			                           btrc_win_pos_union_bits(left.last, right.last), nullable};
		}
		btrc_win_pos_follow(b->program, left.last, right.first);
		return (btrc_win_pos_span){left.nullable ? btrc_win_pos_union_bits(left.first, right.first) : left.first,
		                           right.nullable ? btrc_win_pos_union_bits(right.last, left.last) : right.last, left.nullable && right.nullable};
	}
	if (n->op == btrc_win_pos_star || n->op == btrc_win_pos_plus)
		btrc_win_pos_follow(b->program, left.last, left.first);
	if (n->op != btrc_win_pos_plus && (!b->conditional || b->nodes[n->left].requires_byte)) left.nullable = 1;
	return left;
}

static inline btrc_win_pos_program *btrc_win_pos_compile(const char *pattern, size_t *groups)
{
	if (strlen(pattern) > 255) return NULL;
	const char *escape = strchr(pattern, '\\');
	if (escape && (!escape[1] || !strchr("bB<>", escape[1]) || strchr(escape + 1, '\\'))) return NULL;
	btrc_win_rx_program parsed = {0};
	parsed.flags = REG_EXTENDED;
	btrc_win_rx_parser parser = {&parsed, (const unsigned char *)pattern, 0, 0, 0, 0};
	int root = btrc_win_rx_expression(&parser, 0);
	btrc_win_pos_program *p = NULL;
	if (!parser.error && root && parser.groups && escape) {
		btrc_win_boundary_blocks boundary = {0};
		if (btrc_win_rx_detect_boundary_blocks(&boundary, parsed.nodes, root)) {
			p = (btrc_win_pos_program *)calloc(1, sizeof *p + strlen(pattern) + 1);
			if (p) {
				p->header.kind = btrc_win_group_positions;
				p->boundary_blocks = boundary;
				strcpy((char *)p->edge, pattern);
				*groups = (size_t)parser.groups;
			}
		}
	}
	if (!p && !parser.error && root && parser.groups) {
		int index = 0, assertions = 0, assertion = 0;
		for (int i = 1; i <= parser.nodes; ++i) {
			if (parsed.nodes[i].op == btrc_win_rx_byte) parsed.nodes[i].arg = index++;
			if (parsed.nodes[i].op == btrc_win_rx_assert) {
				assertion = parsed.nodes[i].arg;
				++assertions;
			}
		}
		if (index && index <= btrc_win_pos_limit && (!escape || assertions == 1)) p = (btrc_win_pos_program *)calloc(1, sizeof *p + btrc_win_pos_limit * sizeof *p->edge + strlen(pattern) + 1);
		if (p) {
			btrc_win_pos_builder builder = { .parser = &parser, .program = p, .conditional = assertions == 1 };
			int offset = 0;
			int tree = btrc_win_pos_sequence(&builder, root, &offset, 0);
			if (!builder.conditional && !builder.failed && !btrc_win_pos_dead_boundaries(&builder, tree, 0, 0)) builder.failed = 1;
			if (builder.conditional && !builder.failed) {
				/* Copies of the same assertion at one input boundary always agree.
				   Build both transition tables with identical consuming edge IDs. */
				p->assertion = assertion;
				builder.assertion_true = 1;
				btrc_win_pos_span truth = btrc_win_pos_span_for(&builder, tree);
				btrc_win_pos_bits accept = btrc_win_pos_bit(btrc_win_pos_limit);
				btrc_win_pos_follow(p, truth.last, accept);
				p->when_true = (btrc_win_pos_bits *)malloc((size_t)(p->edges + 1) * sizeof *p->when_true);
				if (!p->when_true) builder.failed = 1;
				else {
					p->when_true[0] = truth.nullable ? btrc_win_pos_union_bits(truth.first, accept) : truth.first;
					for (int i = 0; i < p->edges; ++i) p->when_true[i + 1] = p->edge[i].target;
				}
				p->edges = 0;
				builder.position_count = 0;
				builder.assertion_true = 0;
			}
			btrc_win_pos_span span = btrc_win_pos_span_for(&builder, tree);
			if (builder.failed) { free(p->when_true); free(p); p = NULL; }
			else {
				p->header.kind = btrc_win_group_positions;
				p->initial = span.first;
				p->nullable = span.nullable;
				btrc_win_rx_detect_blocks(&p->ranked_blocks, parsed.nodes, root);
				btrc_win_rx_detect_optional_suffix(&p->optional_suffix, parsed.nodes, root);
				btrc_win_pos_follow(p, span.last, btrc_win_pos_bit(btrc_win_pos_limit));
				size_t bytes = sizeof *p + (size_t)p->edges * sizeof *p->edge + strlen(pattern) + 1;
				btrc_win_pos_program *compact = (btrc_win_pos_program *)realloc(p, bytes);
				if (compact) p = compact;
				strcpy((char *)(p->edge + p->edges), pattern);
				*groups = (size_t)parser.groups;
			}
		}
	}
	free(parsed.nodes);
	return p;
}

static inline btrc_win_pos_bits btrc_win_pos_step(const btrc_win_pos_program *p, btrc_win_pos_bits live, unsigned char byte,
                                                  const btrc_win_pos_bits *at_end)
{
	btrc_win_pos_bits next = {0, 0};
	for (int i = 0; i < p->edges; ++i) {
		const btrc_win_pos_edge *edge = &p->edge[i];
		if (btrc_win_pos_contains(live, edge->source) && btrc_win_set_has(&edge->bytes, byte))
			next = btrc_win_pos_union_bits(next, at_end ? at_end[i + 1] : edge->target);
	}
	return next;
}

enum { btrc_win_pos_origin_limit = 4 };
typedef struct { regoff_t start; btrc_win_pos_bits live; } btrc_win_pos_origin;

static inline int btrc_win_pos_ranked(const btrc_win_pos_program *p, const char *subject, regmatch_t *matches)
{
	if (p->optional_suffix.optional_prefix_limit)
		return btrc_win_regex_match_suffix(&p->optional_suffix, subject, 1, matches);
	return btrc_win_rx_block_match(&p->ranked_blocks, subject, matches);
}

static inline const btrc_win_pos_bits *btrc_win_pos_context(const btrc_win_pos_program *p,
                                                            const unsigned char *s, regoff_t i, int flags)
{
	return p->when_true && btrc_win_rx_boundary_ok(p->assertion, s, i, REG_EXTENDED, flags) ? p->when_true : NULL;
}

static inline int btrc_win_pos_match(const btrc_win_pos_program *p, const char *subject,
                                           size_t count, regmatch_t *matches, int flags)
{
	if (p->boundary_blocks.width)
		return btrc_win_rx_match_boundary_blocks(&p->boundary_blocks, subject, count, matches);
	const unsigned char *s = (const unsigned char *)subject;
	const btrc_win_pos_bits *context = btrc_win_pos_context(p, s, 0, flags);
	btrc_win_pos_origin row[btrc_win_pos_origin_limit];
	int rows = 0;
	regoff_t start = -1, end = -1;
	for (regoff_t i = 0; ; ++i) {
		int admit = end < 0;
		if (admit && (context ? btrc_win_pos_contains(context[0], btrc_win_pos_limit) : p->nullable)) {
			if (!count) return 0;
			start = end = i;
		}
		if (!s[i]) break;
		/* The legacy search admits a new start only at positions absent
		   from the frontier before consuming this byte. */
		btrc_win_pos_bits occupied = {0, 0};
		for (int k = 0; k < rows; ++k) occupied = btrc_win_pos_union_bits(occupied, row[k].live);
		btrc_win_pos_bits first = context ? context[0] : p->initial;
		btrc_win_pos_bits initial = {first.low & ~occupied.low, first.high & ~occupied.high & ~(UINT64_C(1) << 63)};
		int candidates = rows + (admit && btrc_win_pos_any(initial));
		context = btrc_win_pos_context(p, s, i + 1, flags);
		int remaining = 0;
		for (int k = 0; k < candidates; ++k) {
			btrc_win_pos_origin origin = k == rows ? (btrc_win_pos_origin){i, initial} : row[k];
			btrc_win_pos_bits next = btrc_win_pos_step(p, origin.live, s[i], context);
			if (btrc_win_pos_contains(next, btrc_win_pos_limit)) {
				if (!count) return 0;
				/* Distinct accepting origins need the old subgroup ranking.
				   If every acceptance has one origin, its longest end is exact. */
				if (end >= 0 && start != origin.start) return btrc_win_pos_ranked(p, subject, matches);
				start = origin.start;
				end = i + 1;
			}
			next.high &= ~(UINT64_C(1) << 63);
			if (btrc_win_pos_any(next)) {
				/* Pure existence queries do not distinguish origins. */
				if (!count && remaining) row[0].live = btrc_win_pos_union_bits(row[0].live, next);
				else {
					if (remaining == btrc_win_pos_origin_limit) return btrc_win_pos_ranked(p, subject, matches);
					row[remaining++] = (btrc_win_pos_origin){origin.start, next};
				}
			}
		}
		rows = remaining;
		if (!rows && end >= 0) break;
	}
	if (end < 0) return REG_NOMATCH;
	if (count) matches[0] = (regmatch_t){start, end};
	return 0;
}
