/* First-party POSIX ERE/BRE parser and NFA bytecode compiler for Windows.
   Concatenations and alternatives are sibling lists so long flat patterns use
   O(1) C stack depth. Bounded intervals compile into explicit copies under a
   strict instruction budget (RE_DUP_MAX = 255). Each AST node records its
   canonical [entry, exit] bytecode slice for exact POSIX submatch extraction. */
#pragma once
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include "btrc_win_match_bytes.h"

enum btrc_win_rx_op {
	btrc_win_rx_byte,
	btrc_win_rx_assert,
	btrc_win_rx_ref,
	btrc_win_rx_split,
	btrc_win_rx_jump,
	btrc_win_rx_open,
	btrc_win_rx_close,
	btrc_win_rx_mark,
	btrc_win_rx_rank,
	btrc_win_rx_accept,
	btrc_win_rx_group,
	btrc_win_rx_choice,
	btrc_win_rx_repeat
};

enum btrc_win_rx_boundary {
	btrc_win_rx_bol,
	btrc_win_rx_eol,
	btrc_win_rx_bow,
	btrc_win_rx_eow,
	btrc_win_rx_word_boundary,
	btrc_win_rx_nonboundary
};

enum {
	btrc_win_rx_max_nodes = 262144,
	btrc_win_rx_max_code = 262144,
	btrc_win_rx_max_depth = 256,
	btrc_win_rx_dup_max = 255
};

typedef struct {
	enum btrc_win_rx_op op;
	int arg, child, next, min, max, tag;
	int has_group, seq_has_group, compiled;
	int entry, exit, arm_entry, arm_exit;
	btrc_win_byte_set bytes;
} btrc_win_rx_node;

typedef struct {
	enum btrc_win_rx_op op;
	int arg, target;
} btrc_win_rx_inst;

typedef struct {
	btrc_win_rx_node *nodes;
	btrc_win_rx_inst *code;
	int node_count, code_count, code_capacity, root;
	int flags, references, capture_count, tag_count;
	int *group_tags;
	unsigned char *maximize;
} btrc_win_rx_program;

typedef struct {
	btrc_win_rx_program *program;
	const unsigned char *p;
	int nodes, capacity, groups, closed_groups, error;
} btrc_win_rx_parser;

static inline int btrc_win_rx_new(btrc_win_rx_parser *parser, enum btrc_win_rx_op op)
{
	if (parser->error) return 0;
	if (parser->nodes + 1 >= parser->capacity) {
		if (parser->capacity >= btrc_win_rx_max_nodes) {
			parser->error = REG_ESPACE;
			return 0;
		}
		int n = parser->capacity ? parser->capacity * 2 : 32;
		if (n > btrc_win_rx_max_nodes) n = btrc_win_rx_max_nodes;
		btrc_win_rx_node *next = (btrc_win_rx_node *)realloc(parser->program->nodes, (size_t)n * sizeof *next);
		if (!next) {
			parser->error = REG_ESPACE;
			return 0;
		}
		parser->program->nodes = next;
		parser->capacity = n;
	}
	int i = ++parser->nodes;
	memset(&parser->program->nodes[i], 0, sizeof parser->program->nodes[i]);
	parser->program->nodes[i].op = op;
	return i;
}

/* Parentheses, intervals, and GNU-compatible +, ? and | are escaped in BRE. */
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
		if (count > btrc_win_rx_dup_max) {
			parser->error = REG_BADBR;
			return -1;
		}
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
	int group = btrc_win_rx_token(parser, '(');
	if (group) {
		if (depth >= btrc_win_rx_max_depth) {
			parser->error = REG_ESPACE;
			return 0;
		}
		parser->p += group;
		int id = ++parser->groups;
		parser->program->nodes[n].op = btrc_win_rx_group;
		parser->program->nodes[n].arg = id;
		int body = btrc_win_rx_expression(parser, depth + 1);
		if (parser->error) return 0;
		int close = btrc_win_rx_token(parser, ')');
		if (!close) {
			parser->error = REG_EPAREN;
			return 0;
		}
		parser->p += close;
		parser->program->nodes[n].child = body;
		parser->program->nodes[n].max = parser->groups;
		if (id <= 9) parser->closed_groups |= 1 << id;
		return n;
	}
	if ((extended && *parser->p == '*') || btrc_win_rx_token(parser, '+') ||
	    btrc_win_rx_token(parser, '?') || btrc_win_rx_token(parser, '{')) {
		parser->error = REG_BADRPT;
		return 0;
	}
	if (!extended && btrc_win_rx_token(parser, ')')) {
		parser->error = REG_EPAREN;
		return 0;
	}
	unsigned int c = *parser->p++;
	btrc_win_rx_node *node = &parser->program->nodes[n];
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
		if (!c) {
			parser->error = REG_EESCAPE;
			return 0;
		}
		++parser->p;
		if (!extended && c >= '1' && c <= '9') {
			int ref = (int)c - '0';
			if (!(parser->closed_groups & (1 << ref))) {
				parser->error = REG_ESUBREG;
				return 0;
			}
			node->op = btrc_win_rx_ref;
			node->arg = ref;
			parser->program->references |= 1 << ref;
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
			if (c != lower && (parser->program->flags & REG_NEWLINE))
				node->bytes.bits['\n' / 8] &= (unsigned char)~(1u << ('\n' % 8));
			return n;
		}
		if (c == 'x') {
			/* A hex escape denotes its exact byte even under REG_ICASE. */
			fold = 0;
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
				if (*parser->p != '}') {
					parser->error = REG_EBRACE;
					return 0;
				}
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
			int min, max, token;
			if (*parser->p == '*' && !(parser->program->flags & REG_EXTENDED) &&
			    parser->program->nodes[atom].op == btrc_win_rx_assert &&
			    parser->program->nodes[atom].arg == btrc_win_rx_bol) break;
			if (*parser->p == '*') {
				min = 0;
				max = -1;
				++parser->p;
			} else if ((token = btrc_win_rx_token(parser, '+'))) {
				min = 1;
				max = -1;
				parser->p += token;
			} else if ((token = btrc_win_rx_token(parser, '?'))) {
				min = 0;
				max = 1;
				parser->p += token;
			} else if ((token = btrc_win_rx_token(parser, '{'))) {
				parser->p += token;
				if (!*parser->p) {
					parser->error = REG_EBRACE;
					break;
				}
				min = btrc_win_rx_count(parser);
				if (min < 0) {
					if (!parser->error) parser->error = REG_BADBR;
					break;
				}
				max = min;
				if (*parser->p == ',') {
					++parser->p;
					if (!*parser->p) {
						parser->error = REG_EBRACE;
						break;
					}
					if (btrc_win_rx_token(parser, '}')) {
						max = -1;
					} else {
						max = btrc_win_rx_count(parser);
						if (max < 0) {
							if (!parser->error) parser->error = REG_BADBR;
							break;
						}
					}
				}
				token = btrc_win_rx_token(parser, '}');
				if (!token) {
					parser->error = !*parser->p ? REG_EBRACE : REG_BADBR;
					break;
				}
				if (max >= 0 && min > max) {
					parser->error = REG_BADBR;
					break;
				}
				parser->p += token;
			} else {
				break;
			}
			if (++nested + depth > btrc_win_rx_max_depth) {
				parser->error = REG_ESPACE;
				break;
			}
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
		if (rx->code_capacity >= btrc_win_rx_max_code) {
			p->error = REG_ESPACE;
			return -1;
		}
		int capacity = rx->code_capacity ? rx->code_capacity * 2 : 32;
		if (capacity > btrc_win_rx_max_code) capacity = btrc_win_rx_max_code;
		btrc_win_rx_inst *code = (btrc_win_rx_inst *)realloc(rx->code, (size_t)capacity * sizeof *code);
		if (!code) {
			p->error = REG_ESPACE;
			return -1;
		}
		rx->code = code;
		rx->code_capacity = capacity;
	}
	int pc = rx->code_count++;
	rx->code[pc] = (btrc_win_rx_inst){op, arg, target};
	return pc;
}

/* Annotate each node with whether it (or any following sibling) contains a
   live capturing group, and assign tag slots for backref/fallback execution. */
static inline void btrc_win_rx_prepare(btrc_win_rx_parser *p, int first, int depth)
{
	if (depth > btrc_win_rx_max_depth) {
		p->error = REG_ESPACE;
		return;
	}
	btrc_win_rx_program *rx = p->program;
	int last_group_node = 0;
	for (int n = first; n && !p->error; n = rx->nodes[n].next) {
		btrc_win_rx_node *node = &rx->nodes[n];
		if (node->op == btrc_win_rx_group) {
			rx->group_tags[node->arg] = rx->tag_count;
			rx->maximize[rx->tag_count++] = 0;
			rx->maximize[rx->tag_count++] = 1;
			btrc_win_rx_prepare(p, node->child, depth + 1);
			node->has_group = 1;
		} else if (node->op == btrc_win_rx_repeat) {
			node->tag = rx->tag_count;
			rx->maximize[rx->tag_count++] = 1;
			btrc_win_rx_prepare(p, node->child, depth + 1);
			node->has_group = node->max != 0 && rx->nodes[node->child].has_group;
		} else if (node->op == btrc_win_rx_choice) {
			node->tag = rx->tag_count;
			rx->maximize[rx->tag_count++] = 1;
			rx->maximize[rx->tag_count++] = 0;
			int any = 0;
			for (int arm = n; arm && !p->error; arm = rx->nodes[arm].arg) {
				btrc_win_rx_prepare(p, rx->nodes[arm].child, depth + 1);
				if (rx->nodes[arm].child && rx->nodes[rx->nodes[arm].child].seq_has_group) any = 1;
			}
			node->has_group = any;
		} else {
			node->has_group = 0;
		}
		if (node->has_group) last_group_node = n;
	}
	if (last_group_node) {
		for (int n = first; n; n = rx->nodes[n].next) {
			rx->nodes[n].seq_has_group = 1;
			if (n == last_group_node) break;
		}
	}
}

static inline void btrc_win_rx_compile_nodes(btrc_win_rx_parser *p, int n, int depth)
{
	if (depth > btrc_win_rx_max_depth) {
		p->error = REG_ESPACE;
		return;
	}
	btrc_win_rx_program *rx = p->program;
	for (; n && !p->error; n = rx->nodes[n].next) {
		btrc_win_rx_node *node = &rx->nodes[n];
		int record = !node->compiled;
		int start_pc = rx->code_count;
		switch (node->op) {
		case btrc_win_rx_group:
			btrc_win_rx_emit(p, btrc_win_rx_open, node->arg, node->max);
			btrc_win_rx_compile_nodes(p, node->child, depth + 1);
			btrc_win_rx_emit(p, btrc_win_rx_close, node->arg, 0);
			break;
		case btrc_win_rx_choice: {
			int exits = -1, rank = 0;
			for (int arm = n; arm && !p->error; arm = rx->nodes[arm].arg) {
				int another = rx->nodes[arm].arg;
				int split = another ? btrc_win_rx_emit(p, btrc_win_rx_split, 0, 0) : -1;
				int arm_start = rx->code_count;
				btrc_win_rx_compile_nodes(p, rx->nodes[arm].child, depth + 1);
				int arm_end = rx->code_count;
				if (record) {
					rx->nodes[arm].arm_entry = arm_start;
					rx->nodes[arm].arm_exit = arm_end;
				}
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
			break;
		}
		case btrc_win_rx_repeat:
			if (node->max == 0) break;
			for (int i = 0; i < node->min && !p->error; ++i)
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
			if (node->max > node->min) {
				int exits = -1;
				for (int i = node->min; i < node->max && !p->error; ++i) {
					int split = btrc_win_rx_emit(p, btrc_win_rx_split, 0, exits);
					if (split < 0) break;
					exits = split;
					btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				}
				while (exits >= 0) {
					int next = rx->code[exits].target;
					rx->code[exits].target = rx->code_count;
					exits = next;
				}
			} else if (node->max < 0) {
				int loop_head = btrc_win_rx_emit(p, btrc_win_rx_split, 0, 0);
				btrc_win_rx_compile_nodes(p, node->child, depth + 1);
				btrc_win_rx_emit(p, btrc_win_rx_jump, 0, loop_head);
				if (loop_head >= 0) rx->code[loop_head].target = rx->code_count;
			}
			btrc_win_rx_emit(p, btrc_win_rx_mark, node->tag, 0);
			break;
		default:
			btrc_win_rx_emit(p, node->op, node->op == btrc_win_rx_byte ? n : node->arg, 0);
			break;
		}
		if (record) {
			node->compiled = 1;
			node->entry = start_pc;
			node->exit = rx->code_count;
		}
	}
}

static inline void btrc_win_rx_free(btrc_win_rx_program *rx)
{
	if (!rx) return;
	free(rx->group_tags);
	free(rx->maximize);
	free(rx->code);
	free(rx->nodes);
	free(rx);
}

static inline int btrc_win_rx_compile(btrc_win_rx_program **out, size_t *nsub, const char *pattern, int flags)
{
	*out = NULL;
	*nsub = 0;
	if (!pattern) return REG_BADPAT;
	btrc_win_rx_program *rx = (btrc_win_rx_program *)calloc(1, sizeof *rx);
	if (!rx) return REG_ESPACE;
	rx->flags = flags;
	btrc_win_rx_parser parser = {rx, (const unsigned char *)pattern, 0, 0, 0, 0, 0};
	int root = btrc_win_rx_expression(&parser, 0);
	if (!parser.error && *parser.p) parser.error = REG_BADPAT;
	if (!parser.error) {
		rx->root = root;
		rx->node_count = parser.nodes;
		rx->capture_count = parser.groups;
		rx->group_tags = (int *)calloc((size_t)parser.groups + 1, sizeof *rx->group_tags);
		rx->maximize = (unsigned char *)calloc((size_t)parser.nodes * 2 + 2, 1);
		if (!rx->group_tags || !rx->maximize) parser.error = REG_ESPACE;
	}
	if (!parser.error) btrc_win_rx_prepare(&parser, root, 0);
	if (!parser.error) btrc_win_rx_compile_nodes(&parser, root, 0);
	if (!parser.error) btrc_win_rx_emit(&parser, btrc_win_rx_accept, 0, 0);
	if (parser.error) {
		btrc_win_rx_free(rx);
		return parser.error;
	}
	*out = rx;
	*nsub = (size_t)rx->capture_count;
	return 0;
}
