/* A plain, unescaped ERE is one fixed byte sequence. Its prefix table
   advances the search without rescanning prefixes in the subject. */
#pragma once
#include "btrc_win_regex_atom.h"

typedef struct {
	btrc_win_regex_atom atom;
	size_t length;
	int is_atom, at_start, at_end, flags;
	/* Only an unanchored literal needs prefix entries before its owned bytes. */
	size_t prefix[];
} btrc_win_regex_simple;

static inline btrc_win_regex_simple *btrc_win_regex_compile_simple(const char *pattern, int flags)
{
	btrc_win_regex_atom atom = {0};
	const char *end = pattern + strlen(pattern);
	int at_start = *pattern == '^';
	if (at_start) ++pattern;
	int at_end = end > pattern && end[-1] == '$';
	if (at_end) --end;
	int is_atom = btrc_win_regex_parse_atom((const unsigned char *)pattern, (const unsigned char *)end, &atom);
	size_t n = 0, entries = 0;
	if (!is_atom) {
		n = (size_t)(end - pattern);
		if (strcspn(pattern, "\\.^$[](){}+*?|") != n || (!at_start && !at_end && n < 2)) return NULL;
		entries = at_start || at_end ? 0 : n;
		if (n > (SIZE_MAX - sizeof(btrc_win_regex_simple)) / (sizeof(size_t) + 1)) return NULL;
	}
	btrc_win_regex_simple *program = (btrc_win_regex_simple *)malloc(sizeof *program + entries * sizeof(size_t) + n);
	if (!program) return NULL;
	program->atom = atom;
	program->length = n;
	program->is_atom = is_atom;
	program->at_start = at_start;
	program->at_end = at_end;
	program->flags = flags;
	unsigned char *literal = (unsigned char *)(program->prefix + entries);
	if (n) memcpy(literal, pattern, n);
	if (entries) {
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
	if (program->at_start || program->at_end) {
		const char *literal = (const char *)program->prefix;
		size_t start = 0;
		if (program->at_start) {
			if ((program->length && strncmp(subject, literal, program->length)) ||
			    (program->at_end && subject[program->length])) return REG_NOMATCH;
		} else {
			size_t length = strlen(subject);
			if (length < program->length) return REG_NOMATCH;
			start = length - program->length;
			if (program->length && memcmp(subject + start, literal, program->length)) return REG_NOMATCH;
		}
		if (count) btrc_win_regex_set_span(matches, count, (regoff_t)start, (regoff_t)(start + program->length));
		return 0;
	}
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
