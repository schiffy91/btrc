/* POSIX regcomp/regexec and fnmatch over one fixed case table, printed in a
   form that does not depend on the platform's error numbering or messages.

   test_regex_parity.py builds this once against the host C library (glibc on
   Linux, TRE-based libc on macOS) and once against the Windows overlay's
   vendored musl engine (src/runtime/windows/regex.h and fnmatch.h, compiled
   on the host), and requires identical output; it cross-builds the same
   program for windows-x64 and windows-arm64, whose output the win32-native
   job compares with the host library's. Every case is one on which glibc and
   macOS agree in the C locale every btrc program runs in, so the table is
   the matching contract Library.Regex and Library.Pattern rely on. */
#include <fnmatch.h>
#include <regex.h>
#include <stdio.h>
#include <string.h>

typedef struct {
	const char *pattern;
	int flags;
	const char *subject;
	int eflags;
} RegexCase;

typedef struct {
	const char *pattern;
	const char *subject;
	int flags;
} PatternCase;

#define E REG_EXTENDED
#define I REG_ICASE
#define N REG_NEWLINE
#define S REG_NOSUB

static const RegexCase REGEX_CASES[] = {
	/* Literals, search semantics and anchors. */
	{"abc", E, "xxabcxx", 0},
	{"abc", E, "ab", 0},
	{"^abc", E, "abcabc", 0},
	{"^abc", E, "xabc", 0},
	{"abc$", E, "abcabc", 0},
	{"^$", E, "", 0},
	{"^", E, "abc", 0},
	{"$", E, "abc", 0},
	{"^abc", E, "abc", REG_NOTBOL},
	{"abc$", E, "abc", REG_NOTEOL},
	/* Alternation and leftmost-longest. */
	{"a|b", E, "xby", 0},
	{"a|ab", E, "abc", 0},
	{"ab|a", E, "abc", 0},
	{"(a|ab)(c|bcd)", E, "abcd", 0},
	{"x(a|b)*y", E, "xababy", 0},
	{"(cat|category)", E, "category", 0},
	/* Repetition. */
	{"[0-9]+", E, "abc123def", 0},
	{"a*", E, "baaa", 0},
	{"ba*", E, "baaa", 0},
	{"a+", E, "baaa", 0},
	{"ab?c", E, "ac abc", 0},
	{"a{2}", E, "aaaa", 0},
	{"a{2,3}", E, "aaaa", 0},
	{"a{2,}", E, "aaaaa", 0},
	{"(ab){2}", E, "abababx", 0},
	{"b+c", E, "abbcd", 0},
	/* Groups and submatches. */
	{"a(b+)c", E, "xxabbbcyy", 0},
	{"(a)(b)(c)", E, "abc", 0},
	{"((a)b)c", E, "abc", 0},
	{"(a*)(b*)", E, "aabbb", 0},
	{"(a|b)+", E, "abba", 0},
	{"([a-z]+)@([a-z]+)\\.([a-z]+)", E, "user@example.com", 0},
	{"^[a-z]+@[a-z]+\\.[a-z]+$", E, "user@example.com", 0},
	{"^[a-z]+@[a-z]+\\.[a-z]+$", E, "not an email", 0},
	/* Bracket expressions. */
	{"[abc]", E, "xxc", 0},
	{"[^abc]", E, "abcd", 0},
	{"[a-f]+", E, "xyzabcfedg", 0},
	{"[]a]", E, "x]", 0},
	{"[^]a]", E, "]ab", 0},
	{"[a-]", E, "x-", 0},
	{"[[:digit:]]+", E, "ab12c", 0},
	{"[[:alpha:]]+", E, "12abC3", 0},
	{"[[:alnum:]_]+", E, "--a_1--", 0},
	{"[[:space:]]+", E, "a \t\nb", 0},
	{"[[:upper:]]+", E, "abCDe", 0},
	{"[[:lower:]]+", E, "ABcdE", 0},
	{"[[:punct:]]+", E, "ab!?c", 0},
	{"[[:xdigit:]]+", E, "zz0fAgz", 0},
	{"[[:blank:]]+", E, "a \tb", 0},
	{"[[:cntrl:]]", E, "a\x01" "b", 0},
	{"[[:print:]]+", E, "\x01" "ab c\x02", 0},
	{"[[:graph:]]+", E, " ab c", 0},
	/* The dot and newlines. */
	{"a.c", E, "abc", 0},
	{"a.c", E, "a\nc", 0},
	{"a.c", E | N, "a\nc", 0},
	{"^b", E, "a\nb", 0},
	{"^b", E | N, "a\nb", 0},
	{"a$", E | N, "a\nb", 0},
	{"[^x]", E | N, "\n", 0},
	/* Case folding. */
	{"abc", E | I, "xABCx", 0},
	{"[a-c]+", E | I, "xABCx", 0},
	{"[[:lower:]]+", E | I, "ABC", 0},
	/* No submatches requested. */
	{"a(b)c", E | S, "abc", 0},
	{"a(b)c", E | S, "abd", 0},
	/* Escapes. */
	{"a\\.c", E, "abc a.c", 0},
	{"\\(x\\)", E, "(x)", 0},
	{"a\\+", E, "a+", 0},
	{"\\[", E, "x[", 0},
	/* Bytes above ASCII are single characters, never classified. */
	{".", E, "\xc3\xa9", 0},
	{"\xc3\xa9", E, "caf\xc3\xa9", 0},
	{"[[:alpha:]]", E, "\xc3\xa9", 0},
	{"\xc3", E | I, "\xe3", 0},
	{"[\xc3-\xc5]+", E, "a\xc3\xc4\xc5z", 0},
	/* Basic regular expressions. */
	{"a\\(b*\\)c", 0, "xabbcx", 0},
	{"\\(a\\)\\1", 0, "xaax", 0},
	{"a\\{2\\}", 0, "aaa", 0},
	{"a+b", 0, "a+b aab", 0},
	{"a|b", 0, "a|b", 0},
	{"x*", 0, "y", 0},
	/* Invalid patterns. */
	{"[", E, "abc", 0},
	{"(", E, "abc", 0},
	{"[z-a]", E, "abc", 0},
	{"a\\", E, "abc", 0},
	{"[[:nope:]]", E, "abc", 0},
	{"a{2,1}", E, "aa", 0},
	{"\\(", 0, "abc", 0},
	{"a\\{1", 0, "abc", 0},
};

static const PatternCase PATTERN_CASES[] = {
	{"*.txt", "notes.txt", 0},
	{"*.txt", "notes.md", 0},
	{"*", "", 0},
	{"*", "anything", 0},
	{"?", "a", 0},
	{"?", "", 0},
	{"a?c", "abc", 0},
	{"a?c", "ac", 0},
	{"a?c", "abbc", 0},
	{"[abc]x", "bx", 0},
	{"[abc]x", "dx", 0},
	{"[!abc]x", "dx", 0},
	{"[!abc]x", "ax", 0},
	{"[a-c]*", "beta", 0},
	{"[]a]", "]", 0},
	{"[[:digit:]]*", "9lives", 0},
	{"[[:upper:]]", "a", 0},
	{"\\*", "*", 0},
	{"\\*", "x", 0},
	{"\\*", "\\*", FNM_NOESCAPE},
	{"*/b", "a/b", 0},
	{"*", "a/b", FNM_PATHNAME},
	{"*/b", "a/b", FNM_PATHNAME},
	{"a/*/c", "a/b/c", FNM_PATHNAME},
	{"a?b", "a/b", FNM_PATHNAME},
	{"*", ".hidden", 0},
	{"*", ".hidden", FNM_PERIOD},
	{".*", ".hidden", FNM_PERIOD},
	{"a/*", "a/.b", FNM_PATHNAME | FNM_PERIOD},
	{"a/.*", "a/.b", FNM_PATHNAME | FNM_PERIOD},
	{"*.c", "x\xc3\xa9.c", 0},
	{"?", "\xc3", 0},
	{"*a*b*c*", "xaybzc", 0},
	{"*a*b*c*", "xaybz", 0},
};

/* POSIX fixes which conditions are errors, not which code each one gets
   (an unterminated BRE interval is REG_EBRACE on macOS and REG_BADBR in
   musl), so a failed compile prints only that it failed: Library.Regex
   reports every one the same way. */
static const char *match_result(int code)
{
	return code == 0 ? "ok" : code == REG_NOMATCH ? "nomatch" : "error";
}

/* Flags by name: their values differ between C libraries. */
static void print_regex_flags(int flags, int eflags)
{
	printf("%s%s%s%s%s%s", (flags & REG_EXTENDED) ? "E" : "B", (flags & REG_ICASE) ? "i" : "",
		(flags & REG_NEWLINE) ? "n" : "", (flags & REG_NOSUB) ? "s" : "", (eflags & REG_NOTBOL) ? "^" : "",
		(eflags & REG_NOTEOL) ? "$" : "");
}

static void print_pattern_flags(int flags)
{
	printf("%s%s%s", (flags & FNM_PATHNAME) ? "p" : "", (flags & FNM_NOESCAPE) ? "e" : "",
		(flags & FNM_PERIOD) ? "." : "");
}

static void print_quoted(const char *text)
{
	for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
		if (*p < 0x20 || *p >= 0x7f || *p == '\\') {
			printf("\\x%02x", *p);
		} else {
			putchar(*p);
		}
	}
}

int main(void)
{
	size_t count = sizeof REGEX_CASES / sizeof REGEX_CASES[0];
	for (size_t index = 0; index < count; index++) {
		const RegexCase *test = &REGEX_CASES[index];
		regex_t compiled;
		regmatch_t matches[10];
		printf("regex %d /", (int)index);
		print_quoted(test->pattern);
		printf("/");
		print_regex_flags(test->flags, test->eflags);
		printf(" ");
		int status = regcomp(&compiled, test->pattern, test->flags);
		if (status != 0) {
			printf("compile=%s\n", match_result(status));
			continue;
		}
		size_t groups = compiled.re_nsub + 1 < 10 ? compiled.re_nsub + 1 : 10;
		status = regexec(&compiled, test->subject, (test->flags & REG_NOSUB) ? 0 : groups, matches, test->eflags);
		printf("nsub=%d ", (int)compiled.re_nsub);
		if (status != 0) {
			printf("%s\n", match_result(status));
		} else if (test->flags & REG_NOSUB) {
			printf("match\n");
		} else {
			for (size_t group = 0; group < groups; group++) {
				printf("%s%d-%d", group ? " " : "", (int)matches[group].rm_so, (int)matches[group].rm_eo);
			}
			printf("\n");
		}
		regfree(&compiled);
	}
	count = sizeof PATTERN_CASES / sizeof PATTERN_CASES[0];
	for (size_t index = 0; index < count; index++) {
		const PatternCase *test = &PATTERN_CASES[index];
		int status = fnmatch(test->pattern, test->subject, test->flags);
		printf("fnmatch %d ", (int)index);
		print_quoted(test->pattern);
		printf(" ");
		print_quoted(test->subject);
		printf(" ");
		print_pattern_flags(test->flags);
		printf(" %s\n", status == 0 ? "match" : status == FNM_NOMATCH ? "nomatch" : "error");
	}
	printf("posix-matching cases=%d\n", (int)(sizeof REGEX_CASES / sizeof REGEX_CASES[0] + count));
	return 0;
}
