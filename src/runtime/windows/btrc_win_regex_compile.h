/* Parse the byte-oriented BRE/ERE grammar. Concatenations and alternatives
   are sibling lists, so a long flat pattern does not use the C call stack.
   The compiler emits a Thompson program. Bounded intervals compile to
   separate copies, with an instruction budget for nested products. */
#pragma once
#include <stdlib.h>
#include <stdint.h>
#include "btrc_win_match_bytes.h"

enum btrc_win_rx_op {
	btrc_win_rx_byte, btrc_win_rx_assert, btrc_win_rx_ref, btrc_win_rx_split,
	btrc_win_rx_jump, btrc_win_rx_open, btrc_win_rx_close, btrc_win_rx_mark,
	btrc_win_rx_rank, btrc_win_rx_progress, btrc_win_rx_nonempty,
	btrc_win_rx_at_exit, btrc_win_rx_accept, btrc_win_rx_group, btrc_win_rx_choice, btrc_win_rx_repeat
};
enum btrc_win_rx_boundary {
	btrc_win_rx_bol, btrc_win_rx_eol, btrc_win_rx_bow, btrc_win_rx_eow,
	btrc_win_rx_word_boundary, btrc_win_rx_nonboundary
};
typedef struct {
	enum btrc_win_rx_op op;
	int arg, child, next, min, max, tag, optional_tag, guard_tag, nullable, consumes, has_repeat, shares_exit;
	btrc_win_byte_set bytes;
} btrc_win_rx_node;
typedef struct {
	enum btrc_win_rx_op op;
	int arg, target;
} btrc_win_rx_inst;
typedef struct {
	btrc_win_rx_node *nodes;
	btrc_win_rx_inst *code;
	int code_count, code_capacity, flags, references;
	int tag_count, guard_count;
	int *guard_tags;
	/* 0 minimizes and 1 maximizes. A guard (2) and a capture erased by {0}
	   (3) do not participate in path ranking. */
	unsigned char *maximize;
	int *group_tags;
} btrc_win_rx_program;
typedef struct {
	btrc_win_rx_program *program;
	const unsigned char *p;
	int nodes, capacity, groups, error;
} btrc_win_rx_parser;

static inline int btrc_win_rx_new(btrc_win_rx_parser *parser, enum btrc_win_rx_op op)
{
	if (parser->error) return 0;
	if (parser->nodes + 1 >= parser->capacity) {
		if (parser->capacity >= 262144) { parser->error = REG_ESPACE; return 0; }
		int n = parser->capacity ? parser->capacity * 2 : 32;
		btrc_win_rx_node *next = (btrc_win_rx_node *)realloc(parser->program->nodes, (size_t)n * sizeof *next);
		if (!next) { parser->error = REG_ESPACE; return 0; }
		parser->program->nodes = next;
		parser->capacity = n;
	}
	int i = ++parser->nodes;
	memset(&parser->program->nodes[i], 0, sizeof parser->program->nodes[i]);
	parser->program->nodes[i].op = op;
	return i;
}

/* Parentheses, alternatives and intervals are escaped in basic expressions.
   The existing Windows ABI also recognizes escaped +, ? and | in BREs. */
static inline int btrc_win_rx_token(const btrc_win_rx_parser *parser, unsigned char c)
{
	if (parser->program->flags & REG_EXTENDED) return *parser->p == c;
	return parser->p[0] == '\\' && parser->p[1] == c ? 2 : 0;
}

static inline int btrc_win_rx_hex(unsigned char c)
{
	if (c >= '0' && c <= '9') return c - '0';
	unsigned int lower = btrc_win_fold(c);
	return lower >= 'a' && lower <= 'f' ? (int)lower - 'a' + 10 : -1;
}

static inline int btrc_win_rx_count(btrc_win_rx_parser *parser)
{
	int count = 0;
	if (*parser->p < '0' || *parser->p > '9') return -1;
	while (*parser->p >= '0' && *parser->p <= '9') {
		count = 10 * count + (*parser->p++ - '0');
		if (count > 255) { parser->error = REG_BADBR; return -1; }
	}
	return count;
}

static inline int btrc_win_rx_expression(btrc_win_rx_parser *parser, int depth);

static inline int btrc_win_rx_atom(btrc_win_rx_parser *parser, int first, int depth)
{
	int extended = parser->program->flags & REG_EXTENDED;
	int fold = parser->program->flags & REG_ICASE;
	int n = btrc_win_rx_new(parser, btrc_win_rx_byte);
	if (!n) return 0;
	btrc_win_rx_node *node = &parser->program->nodes[n];
	int group = btrc_win_rx_token(parser, '(');
	if (group) {
		if (depth >= 256) { parser->error = REG_ESPACE; return 0; }
		parser->p += group;
		node->op = btrc_win_rx_group;
		node->arg = ++parser->groups;
		int body = btrc_win_rx_expression(parser, depth + 1);
		if (parser->error) return 0;
		node = &parser->program->nodes[n];
		node->child = body;
		node->max = parser->groups;
		int close = btrc_win_rx_token(parser, ')');
		if (!close) { parser->error = REG_EPAREN; return 0; }
		parser->p += close;
		return n;
	}
	if ((extended && *parser->p == '*') || btrc_win_rx_token(parser, '+') ||
	    btrc_win_rx_token(parser, '?') || btrc_win_rx_token(parser, '{')) {
		parser->error = REG_BADRPT;
		return 0;
	}
	if (!extended && btrc_win_rx_token(parser, ')')) { parser->error = REG_EPAREN; return 0; }
	unsigned int c = *parser->p++;
	if (c == '[') {
		int negate = *parser->p == '^';
		enum btrc_win_list_error err = btrc_win_parse_list(&parser->p, &node->bytes, 0, fold);
		static const int errors[] = {0, REG_EBRACK, REG_ERANGE, REG_ECTYPE, REG_ECOLLATE};
		parser->error = errors[err];
		if (negate && (parser->program->flags & REG_NEWLINE))
			node->bytes.bits['\n' / 8] &= (unsigned char)~(1u << ('\n' % 8));
		return n;
	}
	if (c == '.') {
		memset(&node->bytes, 255, sizeof node->bytes);
		if (parser->program->flags & REG_NEWLINE)
			node->bytes.bits['\n' / 8] &= (unsigned char)~(1u << ('\n' % 8));
		return n;
	}
	if ((c == '^' && (extended || first)) ||
	    (c == '$' && (extended || !*parser->p || btrc_win_rx_token(parser, ')') || btrc_win_rx_token(parser, '|')))) {
		node->op = btrc_win_rx_assert;
		node->arg = c == '^' ? btrc_win_rx_bol : btrc_win_rx_eol;
		return n;
	}
	if (c == '\\') {
		c = *parser->p;
		if (!c) { parser->error = REG_EESCAPE; return 0; }
		++parser->p;
		if (!extended && c >= '1' && c <= '9') {
			node->op = btrc_win_rx_ref;
			node->arg = (int)c - '0';
			node->max = node->arg > parser->groups;
			parser->program->references |= 1 << node->arg;
			return n;
		}
		if (c == '<' || c == '>' || c == 'b' || c == 'B') {
			node->op = btrc_win_rx_assert;
			node->arg = c == '<' ? btrc_win_rx_bow : c == '>' ? btrc_win_rx_eow :
			            c == 'b' ? btrc_win_rx_word_boundary : btrc_win_rx_nonboundary;
			return n;
		}
		unsigned int lower = btrc_win_fold(c);
		if (lower == 'd' || lower == 's' || lower == 'w') {
			const char *name = lower == 'd' ? "digit" : lower == 's' ? "space" : "alnum";
			btrc_win_set_class(&node->bytes, (const unsigned char *)name, strlen(name));
			if (lower == 'w') btrc_win_set_add(&node->bytes, '_');
			btrc_win_set_finish(&node->bytes, fold, c != lower);
			return n;
		}
		if (c == 'x') {
			int braces = *parser->p == '{';
			if (braces) ++parser->p;
			c = 0;
			int count = 0, digit;
			while (count < (braces ? 8 : 2) && c <= 0x10ffffU &&
			       (digit = btrc_win_rx_hex(*parser->p)) >= 0) {
				c = c * 16 + (unsigned int)digit;
				++parser->p;
				++count;
			}
			if (braces) {
				if (*parser->p != '}') { parser->error = REG_EBRACE; return 0; }
				++parser->p;
			}
		} else {
			switch (c) {
			case 'a': c = '\a'; break;
			case 'e': c = 27; break;
			case 'f': c = '\f'; break;
			case 'n': c = '\n'; break;
			case 'r': c = '\r'; break;
			case 't': c = '\t'; break;
			}
		}
	}
	if (c <= 255) btrc_win_set_add(&node->bytes, c);
	btrc_win_set_finish(&node->bytes, fold, 0);
	return n;
}

static inline int btrc_win_rx_sequence(btrc_win_rx_parser *parser, int depth)
{
	int first = 0, tail = 0;
	while (*parser->p && !parser->error && !btrc_win_rx_token(parser, '|') &&
	       !(depth && btrc_win_rx_token(parser, ')'))) {
		int atom = btrc_win_rx_atom(parser, !first, depth);
		int nested = 0;
		while (!parser->error) {
			int min, max;
			int token;
			if (*parser->p == '*' && !(parser->program->flags & REG_EXTENDED) &&
			    parser->program->nodes[atom].op == btrc_win_rx_assert &&
			    parser->program->nodes[atom].arg == btrc_win_rx_bol) break;
			if (*parser->p == '*') { min = 0; max = -1; ++parser->p; }
			else if ((token = btrc_win_rx_token(parser, '+'))) { min = 1; max = -1; parser->p += token; }
			else if ((token = btrc_win_rx_token(parser, '?'))) { min = 0; max = 1; parser->p += token; }
			else if ((token = btrc_win_rx_token(parser, '{'))) {
				parser->p += token;
				min = btrc_win_rx_count(parser);
				if (min < 0) { parser->error = REG_BADBR; break; }
				max = min;
				if (*parser->p == ',') { ++parser->p; max = btrc_win_rx_count(parser); }
				token = btrc_win_rx_token(parser, '}');
				if (!token || (max >= 0 && min > max)) { parser->error = REG_BADBR; break; }
				parser->p += token;
			} else break;
			if (++nested + depth > 256) { parser->error = REG_ESPACE; break; }
			int index = btrc_win_rx_new(parser, btrc_win_rx_repeat);
			if (!index) break;
			btrc_win_rx_node *r = &parser->program->nodes[index];
			r->child = atom;
			r->min = min;
			r->max = max;
			atom = index;
		}
		if (parser->error) return 0;
		if (tail) parser->program->nodes[tail].next = atom;
		else first = atom;
		tail = atom;
	}
	return first;
}

static inline int btrc_win_rx_expression(btrc_win_rx_parser *parser, int depth)
{
	int first = btrc_win_rx_sequence(parser, depth);
	if (!btrc_win_rx_token(parser, '|') || parser->error) return first;
	int choice = btrc_win_rx_new(parser, btrc_win_rx_choice);
	if (!choice) return 0;
	parser->program->nodes[choice].child = first;
	int tail = choice;
	while (!parser->error && btrc_win_rx_token(parser, '|')) {
		parser->p += btrc_win_rx_token(parser, '|');
		int branch = btrc_win_rx_new(parser, btrc_win_rx_choice);
		if (!branch) return 0;
		parser->program->nodes[tail].arg = branch;
		int body = btrc_win_rx_sequence(parser, depth);
		parser->program->nodes[branch].child = body;
		tail = branch;
	}
	return choice;
}

static inline int btrc_win_rx_emit(btrc_win_rx_parser *p, enum btrc_win_rx_op op, int arg, int target)
{
	if (p->error) return -1;
	btrc_win_rx_program *rx = p->program;
	if (rx->code_count == rx->code_capacity) {
		if (rx->code_capacity == 262144) { p->error = REG_ESPACE; return -1; }
		int capacity = rx->code_capacity ? rx->code_capacity * 2 : 32;
		btrc_win_rx_inst *code = (btrc_win_rx_inst *)realloc(rx->code, (size_t)capacity * sizeof *code);
		if (!code) { p->error = REG_ESPACE; return -1; }
		rx->code = code;
		rx->code_capacity = capacity;
	}
	int pc = rx->code_count++;
	rx->code[pc] = (btrc_win_rx_inst){op, arg, target};
	return pc;
}

/* The Windows BRE dialect accepts a reference to a group in a different
   alternative as empty. Keep a mask of captures reachable before each
   reference. A repeated body may revisit a group from a prior iteration,
   so the executor must check it at run time. The parser has already
   limited references to groups 1 through 9 and checked the tree depth. */
static inline int btrc_win_rx_reference_paths(btrc_win_rx_program *rx, int n, int available)
{
	for (; n; n = rx->nodes[n].next) {
		btrc_win_rx_node *node = &rx->nodes[n];
		switch (node->op) {
		case btrc_win_rx_group:
			if (node->arg <= 9) available |= 1 << node->arg;
			available = btrc_win_rx_reference_paths(rx, node->child, available);
			break;
		case btrc_win_rx_choice: {
			int combined = available;
			for (int arm = n; arm; arm = rx->nodes[arm].arg)
				combined |= btrc_win_rx_reference_paths(rx, rx->nodes[arm].child, available);
			available = combined;
			break;
		}
		case btrc_win_rx_repeat: {
			int incoming = available;
			if (node->max < 0 || node->max > 1) {
				btrc_win_rx_node *body = &rx->nodes[node->child];
				while (body->op == btrc_win_rx_repeat) body = &rx->nodes[body->child];
				if (body->op == btrc_win_rx_group)
					for (int g = body->arg; g <= body->max && g <= 9; ++g) incoming |= 1 << g;
			}
			if (node->max) available |= btrc_win_rx_reference_paths(rx, node->child, incoming);
			break;
		}
		case btrc_win_rx_ref:
			if (!(available & (1 << node->arg))) node->max = 1;
			break;
		default: break;
		}
	}
	return available;
}

/* Tags are ordered by syntax. A quantified prefix finishes as late as
   possible before the next capture in the concatenation. Within each
   capture, the earlier start, then the later end, wins. */
static inline int btrc_win_rx_nullable(const btrc_win_rx_program *rx, int n)
{
	for (; n; n = rx->nodes[n].next) if (!rx->nodes[n].nullable) return 0;
	return 1;
}

static inline int btrc_win_rx_consumes(const btrc_win_rx_program *rx, int n)
{
	for (; n; n = rx->nodes[n].next) if (rx->nodes[n].consumes) return 1;
	return 0;
}

static inline void btrc_win_rx_tags(btrc_win_rx_parser *p, int n, int depth)
{
	if (depth > 256) { p->error = REG_ESPACE; return; }
	btrc_win_rx_program *rx = p->program;
	for (; n && !p->error; n = rx->nodes[n].next) {
		btrc_win_rx_node *node = &rx->nodes[n];
		if (node->op == btrc_win_rx_group) {
			rx->group_tags[node->arg] = rx->tag_count;
			rx->maximize[rx->tag_count++] = 0;
			rx->maximize[rx->tag_count++] = 1;
			btrc_win_rx_tags(p, node->child, depth + 1);
		} else if (node->op == btrc_win_rx_repeat) {
			node->arg = rx->tag_count;
			rx->maximize[rx->tag_count++] = 1;
			if (node->min > 1) {
				node->tag = rx->tag_count;
				rx->maximize[rx->tag_count++] = 1;
			}
			if ((node->min && node->max > node->min) || (node->min > 1 && node->max < 0)) {
				node->optional_tag = rx->tag_count;
				rx->maximize[rx->tag_count++] = 1;
			}
			btrc_win_rx_tags(p, node->child, depth + 1);
			/* A participating optional copy of a positive-width atom has
			   priority over the preceding mandatory copy's boundary. */
			if (node->min > 1 && node->max > node->min && !btrc_win_rx_nullable(rx, node->child)) {
				int tag = node->optional_tag;
				node->optional_tag = node->tag;
				node->tag = tag;
			}
		} else if (node->op == btrc_win_rx_choice) {
			node->tag = rx->tag_count;
			rx->maximize[rx->tag_count++] = 1;
			rx->maximize[rx->tag_count++] = 0;
			int nullable_arms = 0;
			for (int arm = n; arm; arm = rx->nodes[arm].arg) {
				btrc_win_rx_tags(p, rx->nodes[arm].child, depth + 1);
				nullable_arms += btrc_win_rx_nullable(rx, rx->nodes[arm].child);
			}
			if (nullable_arms > 1) {
				node->guard_tag = rx->tag_count;
				rx->guard_tags[rx->guard_count++] = rx->tag_count;
				rx->maximize[rx->tag_count++] = 2;
			}
		}
		if (node->op == btrc_win_rx_repeat && !node->max) {
			btrc_win_rx_node *child = &rx->nodes[node->child];
			if (child->op == btrc_win_rx_group)
				for (int g = child->arg; g <= child->max; ++g)
					rx->maximize[rx->group_tags[g]] = 3;
		}
		switch (node->op) {
		case btrc_win_rx_group:
			node->shares_exit = 1;
			for (int c = node->child; c; c = rx->nodes[c].next)
				node->shares_exit &= rx->nodes[c].shares_exit;
			/* fall through */
		case btrc_win_rx_repeat:
			if (node->op == btrc_win_rx_repeat) node->shares_exit = !node->max;
			node->has_repeat = node->op == btrc_win_rx_repeat;
			for (int child = node->child; child; child = rx->nodes[child].next)
				node->has_repeat |= rx->nodes[child].has_repeat;
			node->nullable = (node->op == btrc_win_rx_repeat && !node->min) ||
			                 btrc_win_rx_nullable(rx, node->child);
			node->consumes = (node->op == btrc_win_rx_group || node->max != 0) &&
			                 btrc_win_rx_consumes(rx, node->child);
			break;
		case btrc_win_rx_choice:
			for (int arm = n; arm; arm = rx->nodes[arm].arg) {
				for (int child = rx->nodes[arm].child; child; child = rx->nodes[child].next)
					node->has_repeat |= rx->nodes[child].has_repeat;
				node->nullable |= btrc_win_rx_nullable(rx, rx->nodes[arm].child);
				node->consumes |= btrc_win_rx_consumes(rx, rx->nodes[arm].child);
			}
			break;
		default:
			node->shares_exit = node->op == btrc_win_rx_assert;
			node->nullable = node->op != btrc_win_rx_byte;
			node->consumes = node->op != btrc_win_rx_assert;
			break;
		}
	}
}

/* Captures with no separately tagged position share the end of the
   enclosing alternative, even when another arm consumed the input. */
static inline void btrc_win_rx_choice_exits(btrc_win_rx_parser *p, int first)
{
	btrc_win_rx_program *rx = p->program;
	for (int arm = first; arm; arm = rx->nodes[arm].arg) {
		int suffix = rx->nodes[arm].child;
		for (int n = suffix; n; n = rx->nodes[n].next) {
			btrc_win_rx_node *node = &rx->nodes[n];
			if (!node->shares_exit &&
			    !(node->op == btrc_win_rx_repeat && rx->nodes[node->child].shares_exit))
				suffix = node->next;
		}
		for (int n = suffix; n; n = rx->nodes[n].next) {
			btrc_win_rx_node *node = &rx->nodes[n];
			if (node->op == btrc_win_rx_repeat && node->max)
				node = &rx->nodes[node->child];
			if (node->op == btrc_win_rx_group)
				btrc_win_rx_emit(p, btrc_win_rx_at_exit, node->arg, node->max);
		}
	}
}

static inline void btrc_win_rx_compile_nodes(btrc_win_rx_parser *p, int n, int depth)
{
	if (depth > 256) { p->error = REG_ESPACE; return; }
	btrc_win_rx_program *rx = p->program;
	for (; n && !p->error; n = rx->nodes[n].next) {
		btrc_win_rx_node *node = &rx->nodes[n];
		switch (node->op) {
		case btrc_win_rx_group:
			btrc_win_rx_emit(p, btrc_win_rx_open, node->arg, node->max);
			btrc_win_rx_compile_nodes(p, node->child, depth + 1);
			btrc_win_rx_emit(p, btrc_win_rx_close, node->arg, 0);
			break;
		case btrc_win_rx_choice: {
			/* The Windows overlay checks the first nullable arm on an empty
			   transition. Later arms remain eligible when they consume bytes. */
			if (!node->consumes) {
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				btrc_win_rx_choice_exits(p, n);
				break;
			}
			int exits = -1, rank = 0, earlier_nullable = 0;
			for (int arm = n; arm && !p->error; arm = rx->nodes[arm].arg) {
				int another = rx->nodes[arm].arg;
				int split = another ? btrc_win_rx_emit(p, btrc_win_rx_split, 0, 0) : -1;
				int nullable = btrc_win_rx_nullable(rx, rx->nodes[arm].child);
				int require_byte = node->guard_tag && earlier_nullable && nullable;
				if (require_byte) btrc_win_rx_emit(p, btrc_win_rx_mark, node->guard_tag, 0);
				btrc_win_rx_compile_nodes(p, rx->nodes[arm].child, depth + 1);
				if (require_byte) btrc_win_rx_emit(p, btrc_win_rx_progress, node->guard_tag, 0);
				earlier_nullable |= nullable;
				btrc_win_rx_emit(p, btrc_win_rx_mark, node->tag, 0);
				btrc_win_rx_emit(p, btrc_win_rx_rank, node->tag + 1, rank++);
				if (split >= 0) {
					exits = btrc_win_rx_emit(p, btrc_win_rx_jump, 0, exits);
					rx->code[split].target = rx->code_count;
				}
			}
			while (exits >= 0) {
				int next = rx->code[exits].target;
				rx->code[exits].target = rx->code_count;
				exits = next;
			}
			btrc_win_rx_choice_exits(p, n);
			break;
		}
		case btrc_win_rx_repeat: {
			btrc_win_rx_node *child = &rx->nodes[node->child];
			if (!child->consumes && node->max != 0 && node->max <= 1) {
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				break;
			}
			if (child->nullable && !node->min &&
			    (node->max == 1 || node->max < 0)) {
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				if (node->max == 1) break;
			}
			for (int i = 0; i < node->min && !p->error; ++i) {
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				if (i == node->min - 2) btrc_win_rx_emit(p, btrc_win_rx_mark, node->tag, 0);
				else btrc_win_rx_emit(p, btrc_win_rx_jump, 0, rx->code_count + 1);
			}
			if (node->min > 1 && node->max < 0 && child->op == btrc_win_rx_group && child->nullable) {
				/* A nullable open interval takes its first optional copy even
				   when empty. This evaluates its assertions and captures.
				   All subsequent optional copies must consume a byte. */
				btrc_win_rx_emit(p, btrc_win_rx_mark, node->optional_tag, 0);
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
			}
			int exits = -1;
			for (int i = node->min; !p->error && (node->max < 0 || i < node->max); ++i) {
				int split = btrc_win_rx_emit(p, btrc_win_rx_split, 0, exits);
				if (split < 0) break;
				exits = split;
				if (node->optional_tag)
					btrc_win_rx_emit(p, btrc_win_rx_mark, node->optional_tag, 0);
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				int counted = node->max > 1 || (node->min > 1 && node->max < 0);
				if (counted && child->op == btrc_win_rx_group && child->nullable &&
				    (child->consumes || child->has_repeat))
					btrc_win_rx_emit(p, btrc_win_rx_nonempty, child->arg, 0);
				if (node->max < 0) { btrc_win_rx_emit(p, btrc_win_rx_jump, 0, split); break; }
			}
			while (exits >= 0) {
				int next = rx->code[exits].target;
				rx->code[exits].target = rx->code_count;
				exits = next;
			}
			if (node->max && child->op == btrc_win_rx_group && child->shares_exit)
				btrc_win_rx_emit(p, btrc_win_rx_at_exit, child->arg, child->max);
			/* An unquantified capture begins after the greedy prefix.
			   A repeated, nullable capture can span that prefix itself. */
			btrc_win_rx_node *next = node->next ? &rx->nodes[node->next] : NULL;
			if (!(child->op == btrc_win_rx_byte && next && next->op == btrc_win_rx_repeat &&
			      rx->nodes[next->child].op == btrc_win_rx_group && rx->nodes[next->child].nullable))
				btrc_win_rx_emit(p, btrc_win_rx_mark, node->arg, 0);
			break;
		}
		default:
			btrc_win_rx_emit(p, node->op, node->op == btrc_win_rx_byte ? n : node->arg, node->max);
			break;
		}
	}
}

static inline void btrc_win_regfree(regex_t *re)
{
	btrc_win_rx_program *rx = (btrc_win_rx_program *)re->__opaque;
	if (!rx) return;
	free(rx->group_tags);
	free(rx->guard_tags);
	free(rx->maximize);
	free(rx->code);
	free(rx->nodes);
	free(rx);
	re->__opaque = NULL;
}

/* This dispatch step enables only consuming bytes, concatenation, plain
   alternatives and a single repetition on a byte. It does not enable
   submatch rankings, assertions, backreferences or nested repetitions. */
static inline int btrc_win_rx_flat_eligible(const btrc_win_rx_parser *parser)
{
	const btrc_win_rx_node *nodes = parser->program->nodes;
	for (int i = 1; i <= parser->nodes; ++i) {
		const btrc_win_rx_node *node = &nodes[i];
		if (node->op == btrc_win_rx_byte) continue;
		if (node->op == btrc_win_rx_repeat && nodes[node->child].op == btrc_win_rx_byte) continue;
		if (node->op == btrc_win_rx_choice && node->child) continue;
		return 0;
	}
	return parser->nodes > 0;
}

static inline int btrc_win_regcomp(regex_t *restrict re, const char *restrict pattern, int flags)
{
	memset(re, 0, sizeof *re);
	btrc_win_rx_program *rx = (btrc_win_rx_program *)calloc(1, sizeof *rx);
	if (!rx) return REG_ESPACE;
	re->__opaque = rx;
	rx->flags = flags;
	btrc_win_rx_parser parser = {rx, (const unsigned char *)pattern, 0, 0, 0, 0};
	int root = btrc_win_rx_expression(&parser, 0);
	if (!parser.error && !btrc_win_rx_flat_eligible(&parser)) parser.error = REG_BADPAT;
	if (!parser.error && parser.groups < 9 && (rx->references >> (parser.groups + 1)))
		parser.error = REG_ESUBREG;
	if (!parser.error) {
		rx->group_tags = (int *)calloc((size_t)parser.groups + 1, sizeof *rx->group_tags);
		rx->maximize = (unsigned char *)calloc((size_t)parser.nodes * 3 + 1, 1);
		rx->guard_tags = (int *)calloc((size_t)parser.nodes + 1, sizeof *rx->guard_tags);
		if (!rx->group_tags || !rx->maximize || !rx->guard_tags) parser.error = REG_ESPACE;
	}
	if (!parser.error) btrc_win_rx_tags(&parser, root, 0);
	if (!parser.error && rx->references) btrc_win_rx_reference_paths(rx, root, 0);
	if (!parser.error) btrc_win_rx_compile_nodes(&parser, root, 0);
	if (!parser.error) btrc_win_rx_emit(&parser, btrc_win_rx_accept, 0, 0);
	if (parser.error) btrc_win_regfree(re);
	else re->re_nsub = (size_t)parser.groups;
	return parser.error;
}
