/* A position automaton for Windows EREs whose outer group can always match
   empty. Their public match starts at zero. Counted repetitions inside
   another repetition can share consuming positions with their suffix,
   which changes the byte language of the historical Windows provider. */
#pragma once
#include "btrc_win_regex_compile.h"

enum { btrc_win_pos_limit = 63, btrc_win_pos_nodes = 256 };
#define BTRC_WIN_POS_ACCEPT (UINT64_C(1) << btrc_win_pos_limit)

typedef struct {
	uint64_t source, target;
	btrc_win_byte_set bytes;
} btrc_win_pos_edge;

typedef struct {
	btrc_win_group_header header;
	uint64_t initial;
	int edges;
	btrc_win_pos_edge edge[btrc_win_pos_limit];
	char pattern[];
} btrc_win_pos_program;

enum btrc_win_pos_op { btrc_win_pos_empty, btrc_win_pos_byte, btrc_win_pos_cat,
                       btrc_win_pos_union, btrc_win_pos_optional, btrc_win_pos_star, btrc_win_pos_plus };
typedef struct {
	enum btrc_win_pos_op op;
	int left, right, width;
} btrc_win_pos_node;

typedef struct {
	btrc_win_rx_parser *parser;
	btrc_win_pos_program *program;
	btrc_win_pos_node nodes[btrc_win_pos_nodes];
	int used, extra, failed;
} btrc_win_pos_builder;

/* Until building finishes, a byte leaf names its source syntax node and
   its consuming position. A composite names its children and counts the
   byte leaves a repeated copy would contain. Index zero denotes epsilon. */
static inline int btrc_win_pos_new(btrc_win_pos_builder *b, enum btrc_win_pos_op op, int left, int right)
{
	if (b->failed) return 0;
	if (b->used >= btrc_win_pos_nodes - 1 || (op == btrc_win_pos_byte && right >= btrc_win_pos_limit)) {
		b->failed = 1;
		return 0;
	}
	int width = op == btrc_win_pos_byte ? 1 : b->nodes[left].width + b->nodes[right].width;
	int id = ++b->used;
	b->nodes[id] = (btrc_win_pos_node){op, left, right, width};
	return id;
}

static inline int btrc_win_pos_copy(btrc_win_pos_builder *b, int id, int offset)
{
	if (!id || !offset || b->failed) return id;
	btrc_win_pos_node n = b->nodes[id];
	if (n.op == btrc_win_pos_byte) return btrc_win_pos_new(b, n.op, n.left, n.right + offset);
	int left = btrc_win_pos_copy(b, n.left, offset);
	int right = btrc_win_pos_copy(b, n.right, offset);
	return btrc_win_pos_new(b, n.op, left, right);
}

static inline int btrc_win_pos_sequence(btrc_win_pos_builder *b, int id, int *offset, int depth);

static inline int btrc_win_pos_repeat(btrc_win_pos_builder *b, const btrc_win_rx_node *n, int *offset, int depth)
{
	if (n->max == 0 || b->parser->program->nodes[n->child].op == btrc_win_rx_repeat) {
		b->failed = 1;
		return 0;
	}
	int counted = n->min > 1 || n->max > 1;
	int inner_offset = counted ? 0 : *offset;
	int child = btrc_win_pos_sequence(b, n->child, &inner_offset, depth + 1);
	if (b->failed) return 0;
	if (!counted) {
		if (!depth) *offset = b->extra;
		if (n->max == 1 && n->min == 1) return child;
		return btrc_win_pos_new(b, n->max == 1 ? btrc_win_pos_optional :
		                           n->min ? btrc_win_pos_plus : btrc_win_pos_star, child, 0);
	}
	int copies = n->max < 0 ? n->min + 1 : n->max;
	int width = b->nodes[child].width;
	if (!width || copies > btrc_win_pos_limit / width) { b->failed = 1; return 0; }
	int required = 0, tail = 0;
	for (int i = 0; i < copies && !b->failed; ++i) {
		int copy = btrc_win_pos_copy(b, child, *offset + i * width);
		if (i < n->min) required = required ? btrc_win_pos_new(b, btrc_win_pos_cat, required, copy) : copy;
		else if (n->max < 0) tail = btrc_win_pos_new(b, btrc_win_pos_star, copy, 0);
		else {
			if (tail) copy = btrc_win_pos_new(b, btrc_win_pos_cat, copy, tail);
			tail = btrc_win_pos_new(b, btrc_win_pos_optional, copy, 0);
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

/* First is a set of consuming positions. Last indexes individual byte
   edges because two occurrences at one position may accept different
   bytes and lead to different suffixes. */
typedef struct { uint64_t first, last; int nullable; } btrc_win_pos_span;

static inline void btrc_win_pos_follow(btrc_win_pos_program *p, uint64_t edges, uint64_t next)
{
	for (int i = 0; edges; ++i, edges >>= 1)
		if (edges & 1) p->edge[i].target |= next;
}

static inline btrc_win_pos_span btrc_win_pos_span_for(btrc_win_pos_builder *b, int id)
{
	btrc_win_pos_span empty = {0, 0, 1};
	if (!id || b->failed) return empty;
	const btrc_win_pos_node *n = &b->nodes[id];
	if (n->op == btrc_win_pos_byte) {
		btrc_win_pos_program *p = b->program;
		if (p->edges == btrc_win_pos_limit) { b->failed = 1; return empty; }
		int slot = p->edges++;
		uint64_t position = UINT64_C(1) << n->right;
		p->edge[slot] = (btrc_win_pos_edge){position, 0, b->parser->program->nodes[n->left].bytes};
		return (btrc_win_pos_span){position, UINT64_C(1) << slot, 0};
	}
	btrc_win_pos_span left = btrc_win_pos_span_for(b, n->left);
	if (n->op == btrc_win_pos_cat || n->op == btrc_win_pos_union) {
		btrc_win_pos_span right = btrc_win_pos_span_for(b, n->right);
		if (n->op == btrc_win_pos_union)
			return (btrc_win_pos_span){left.first | right.first, left.last | right.last, left.nullable || right.nullable};
		btrc_win_pos_follow(b->program, left.last, right.first);
		return (btrc_win_pos_span){left.first | (left.nullable ? right.first : 0),
		                           right.last | (right.nullable ? left.last : 0), left.nullable && right.nullable};
	}
	if (n->op == btrc_win_pos_star || n->op == btrc_win_pos_plus)
		btrc_win_pos_follow(b->program, left.last, left.first);
	if (n->op != btrc_win_pos_plus) left.nullable = 1;
	return left;
}

/* A single literal, range or named class occupies one consuming leaf
   when copied. Other bracket layouts can use a different copy stride. */
static inline int btrc_win_pos_supported(const char *p)
{
	for (; *p; ++p) {
		if (*p == '$' || *p == '^' || *p == '\\') return 0;
		if (*p != '[') continue;
		if (p[1] == '[' && p[2] == ':') {
			const char *end = strstr(p + 3, ":]]");
			if (!end) return 0;
			for (const char *c = p + 3; c < end; ++c)
				if (*c < 'a' || *c > 'z') return 0;
			p = end + 2;
		} else {
			if (!p[1] || p[1] == '^' || p[1] == '[' || p[1] == ']') return 0;
			if (p[2] == ']') p += 2;
			else if (p[2] == '-' && p[3] && p[3] != '[' && p[3] != ']' && p[4] == ']') p += 4;
			else return 0;
		}
	}
	return 1;
}

static inline btrc_win_pos_program *btrc_win_pos_compile(const char *pattern, size_t *groups)
{
	if (*pattern != '(' || strlen(pattern) > 255 || !btrc_win_pos_supported(pattern)) return NULL;
	btrc_win_rx_program parsed = {0};
	parsed.flags = REG_EXTENDED;
	btrc_win_rx_parser parser = {&parsed, (const unsigned char *)pattern, 0, 0, 0, 0};
	int root = btrc_win_rx_expression(&parser, 0);
	btrc_win_pos_program *p = NULL;
	if (!parser.error && root && parser.groups) {
		int index = 0;
		for (int i = 1; i <= parser.nodes; ++i)
			if (parsed.nodes[i].op == btrc_win_rx_byte) parsed.nodes[i].arg = index++;
		if (index && index <= btrc_win_pos_limit) p = (btrc_win_pos_program *)calloc(1, sizeof *p + strlen(pattern) + 1);
		if (p) {
			btrc_win_pos_builder builder = { .parser = &parser, .program = p };
			int offset = 0;
			int tree = btrc_win_pos_sequence(&builder, root, &offset, 0);
			btrc_win_pos_span span = btrc_win_pos_span_for(&builder, tree);
			if (builder.failed || !span.nullable) { free(p); p = NULL; }
			else {
				p->header.kind = btrc_win_group_positions;
				p->initial = span.first;
				btrc_win_pos_follow(p, span.last, BTRC_WIN_POS_ACCEPT);
				strcpy(p->pattern, pattern);
				*groups = (size_t)parser.groups;
			}
		}
	}
	free(parsed.nodes);
	return p;
}

static inline int btrc_win_pos_match(const btrc_win_pos_program *p, const char *subject,
                                     size_t count, regmatch_t *matches)
{
	if (!count) return 0;
	uint64_t live = p->initial;
	regoff_t end = 0;
	for (regoff_t i = 0; live && subject[i]; ++i) {
		uint64_t next = 0;
		for (int j = 0; j < p->edges; ++j) {
			const btrc_win_pos_edge *edge = &p->edge[j];
			if ((edge->source & live) && btrc_win_set_has(&edge->bytes, (unsigned char)subject[i])) next |= edge->target;
		}
		if (next & BTRC_WIN_POS_ACCEPT) end = i + 1;
		live = next & ~BTRC_WIN_POS_ACCEPT;
	}
	matches[0] = (regmatch_t){0, end};
	return 0;
}

#undef BTRC_WIN_POS_ACCEPT
