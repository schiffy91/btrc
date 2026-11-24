/* A plain, unescaped ERE is one fixed byte sequence. Its prefix table
   advances the search without rescanning prefixes in the subject. */
#pragma once
#include "btrc_win_regex_atom.h"

typedef struct {
	btrc_win_regex_atom atom;
	size_t length;
	/* The owned literal bytes follow length prefix entries. */
	size_t prefix[];
} btrc_win_regex_simple;

static inline btrc_win_regex_simple *btrc_win_regex_compile_simple(const char *pattern)
{
	btrc_win_regex_atom atom = {0};
	size_t n = 0;
	if (!btrc_win_regex_parse_atom(pattern, &atom)) {
		n = strcspn(pattern, "\\.^$[](){}+*?|");
		if (n < 2 || pattern[n] || n > (SIZE_MAX - sizeof(btrc_win_regex_simple)) / (sizeof(size_t) + 1)) return NULL;
	}
	btrc_win_regex_simple *program = (btrc_win_regex_simple *)malloc(sizeof *program + n * (sizeof(size_t) + 1));
	if (!program) return NULL;
	program->atom = atom;
	program->length = n;
	if (n) {
		unsigned char *literal = (unsigned char *)(program->prefix + n);
		memcpy(literal, pattern, n);
		program->prefix[0] = 0;
		for (size_t i = 1, common = 0; i < n; ++i) {
			while (common && literal[i] != literal[common]) common = program->prefix[common - 1];
			if (literal[i] == literal[common]) ++common;
			program->prefix[i] = common;
		}
	}
	return program;
}

static inline int btrc_win_regex_match_literal(const btrc_win_regex_simple *program, const char *subject,
                                               size_t count, regmatch_t *matches)
{
	const unsigned char *literal = (const unsigned char *)(program->prefix + program->length);
	const unsigned char *text = (const unsigned char *)subject;
	size_t common = 0;
	for (size_t i = 0; text[i]; ++i) {
		while (common && text[i] != literal[common]) common = program->prefix[common - 1];
		if (text[i] == literal[common]) ++common;
		if (common == program->length) {
			if (count) btrc_win_regex_set_span(matches, count, (regoff_t)(i + 1 - common), (regoff_t)(i + 1));
			return 0;
		}
	}
	return REG_NOMATCH;
}
