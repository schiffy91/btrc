/* First-party Windows POSIX regex semantics, error-code, and ReDoS bounds check.
   Exercises IEEE Std 1003.1 leftmost-longest submatch disambiguation, BRE
   backreferences, all regcomp error codes, regerror sizing, and pathological
   patterns that defeat backtracking engines. */
#include <regex.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void expect_match(const char *pat, int cflags, const char *sub, int eflags,
                         size_t nmatch, const regoff_t *expected)
{
	regex_t re;
	regmatch_t m[8];
	int rc = regcomp(&re, pat, cflags);
	if (rc != 0) {
		fprintf(stderr, "regcomp failed (%d) for /%s/\n", rc, pat);
		exit(1);
	}
	rc = regexec(&re, sub, nmatch, m, eflags);
	regfree(&re);
	if (rc != 0) {
		fprintf(stderr, "regexec failed (%d) for /%s/ on \"%s\"\n", rc, pat, sub);
		exit(1);
	}
	for (size_t i = 0; i < nmatch; ++i) {
		if (m[i].rm_so != expected[2 * i] || m[i].rm_eo != expected[2 * i + 1]) {
			fprintf(stderr, "mismatch /%s/ on \"%s\" group %zu: got [%ld,%ld), want [%ld,%ld)\n",
			        pat, sub, i, (long)m[i].rm_so, (long)m[i].rm_eo,
			        (long)expected[2 * i], (long)expected[2 * i + 1]);
			exit(1);
		}
	}
}

static void expect_status(const char *pat, int cflags, const char *sub, int eflags, int want_exec)
{
	regex_t re;
	int rc = regcomp(&re, pat, cflags);
	if (rc != 0) {
		fprintf(stderr, "regcomp failed (%d) for /%s/\n", rc, pat);
		exit(1);
	}
	rc = regexec(&re, sub, 0, NULL, eflags);
	regfree(&re);
	if (rc != want_exec) {
		fprintf(stderr, "status mismatch /%s/ on \"%s\": got %d, want %d\n", pat, sub, rc, want_exec);
		exit(1);
	}
}

static void expect_compile_err(const char *pat, int cflags, int want_code)
{
	regex_t re;
	int rc = regcomp(&re, pat, cflags);
	if (rc != want_code) {
		fprintf(stderr, "compile error mismatch /%s/: got %d, want %d\n", pat, rc, want_code);
		exit(1);
	}
	char buf[64];
	size_t need = regerror(rc, &re, NULL, 0);
	size_t got = regerror(rc, &re, buf, sizeof buf);
	if (need != got || need < 2 || strlen(buf) + 1 != need) {
		fprintf(stderr, "regerror contract failed for code %d\n", rc);
		exit(1);
	}
}

int main(void)
{
	/* Exact POSIX leftmost-longest disambiguation (no TRE nested-interval or start-overwrite bugs). */
	{ const regoff_t e[] = {0, 0, -1, -1, -1, -1}; expect_match("((a{2})?b)?", REG_EXTENDED, "ab", 0, 3, e); }
	{ const regoff_t e[] = {0, 3, 0, 3, 0, 2}; expect_match("((a{2})?b)?", REG_EXTENDED, "aab", 0, 3, e); }
	{ const regoff_t e[] = {0, 0, -1, -1, -1, -1}; expect_match("((b{1,3}){2,3}|.x){0,2}", REG_EXTENDED, "ab", 0, 3, e); }
	{ const regoff_t e[] = {0, 5, 0, 1}; expect_match("([[:digit:]])+.{2,4}", REG_EXTENDED, "1x12345", 0, 2, e); }
	{ const regoff_t e[] = {0, 4, 0, 4, 2, 4}; expect_match("((..){1,3})+", REG_EXTENDED, "abcde", 0, 3, e); }
	{ const regoff_t e[] = {0, 4, 0, 0, 0, 0, -1, -1, 3, 4}; expect_match("(((b)?){2})?([abc]){2,4}", REG_EXTENDED, "abbba", 0, 5, e); }
	{ const regoff_t e[] = {0, 4, 3, 4}; expect_match("(a|aa|aaa)*", REG_EXTENDED, "aaaa", 0, 2, e); }
	{ const regoff_t e[] = {0, 3, 2, 3}; expect_match("(a|aa)*", REG_EXTENDED, "aaa", 0, 2, e); }
	{ const regoff_t e[] = {0, 4, 0, 4, 0, 2, 2, 4}; expect_match("((a|ab)(b|ab))*", REG_EXTENDED, "abab", 0, 4, e); }
	{ const regoff_t e[] = {0, 2, 0, 2}; expect_match("(a|aa){1,2}", REG_EXTENDED, "aa", 0, 2, e); }
	{ const regoff_t e[] = {0, 2, 2, 2}; expect_match("a*(a*)*", REG_EXTENDED, "aa", 0, 2, e); }
	{ const regoff_t e[] = {0, 1, 0, 1, -1, -1}; expect_match("(a|())", REG_EXTENDED, "a", 0, 3, e); }
	{ const regoff_t e[] = {0, 0, -1, -1}; expect_match("(a){0}", REG_EXTENDED, "a", 0, 2, e); }
	{ const regoff_t e[] = {1, 2, -1, -1}; expect_match("(^)?a", REG_EXTENDED, "ba", 0, 2, e); }
	{ const regoff_t e[] = {0, 1, 0, 0}; expect_match("($|^)a", REG_EXTENDED, "a", 0, 2, e); }
	{ const regoff_t e[] = {0, 0, 0, 0}; expect_match("($|)", REG_EXTENDED, "a", 0, 2, e); }
	{ const regoff_t e[] = {0, 2, 1, 2, -1, -1}; expect_match("((a)|b)+", REG_EXTENDED, "ab", 0, 3, e); }
	{ const regoff_t e[] = {0, 3, 0, 2, 2, 3}; expect_match("(a|ab)(bc|c)", REG_EXTENDED, "abc", 0, 3, e); }
	{ const regoff_t e[] = {0, 4, 0, 1, 1, 4}; expect_match("(a|ab)(c|bcd)", REG_EXTENDED, "abcd", 0, 3, e); }
	{ const regoff_t e[] = {0, 2, 0, 1}; expect_match("\\(a*\\)\\1", 0, "aaa", 0, 2, e); }
	{ const regoff_t e[] = {1, 4, 1, 2}; expect_match("\\(a*\\)b\\1", 0, "aaba", 0, 2, e); }
	{ const regoff_t e[] = {0, 2, 0, 1}; expect_match("\\(a\\)\\1", REG_ICASE, "aA", 0, 2, e); }
	{ const regoff_t e[] = {1, 2}; expect_match("[[.a.]-[.c.]]", REG_EXTENDED, "xb", 0, 1, e); }
	{ const regoff_t e[] = {1, 4}; expect_match("[[=a=]]+", REG_EXTENDED, "xaaa", 0, 1, e); }
	expect_status("\\(\\(a\\)\\|b\\)\\2", 0, "b", 0, REG_NOMATCH);
	expect_status("\\(a\\)\\{0\\}\\1", 0, "a", 0, REG_NOMATCH);

	/* All regcomp diagnostic codes. */
	expect_compile_err("[", REG_EXTENDED, REG_EBRACK);
	expect_compile_err("[a-", REG_EXTENDED, REG_EBRACK);
	expect_compile_err("(", REG_EXTENDED, REG_EPAREN);
	expect_compile_err("\\(", 0, REG_EPAREN);
	expect_compile_err("\\)", 0, REG_EPAREN);
	expect_compile_err("a\\", REG_EXTENDED, REG_EESCAPE);
	expect_compile_err("[[:nope:]]", REG_EXTENDED, REG_ECTYPE);
	expect_compile_err("[[.ch.]]", REG_EXTENDED, REG_ECOLLATE);
	expect_compile_err("[z-a]", REG_EXTENDED, REG_ERANGE);
	expect_compile_err("[0-[:alpha:]]", REG_EXTENDED, REG_ERANGE);
	expect_compile_err("a{1,2", REG_EXTENDED, REG_EBRACE);
	expect_compile_err("a\\{1", 0, REG_EBRACE);
	expect_compile_err("a{2,1}", REG_EXTENDED, REG_BADBR);
	expect_compile_err("a{256}", REG_EXTENDED, REG_BADBR);
	expect_compile_err("*a", REG_EXTENDED, REG_BADRPT);
	expect_compile_err("\\(a\\)\\2", 0, REG_ESUBREG);
	expect_compile_err("\\(\\1\\)", 0, REG_ESUBREG);
	expect_compile_err("(((a{255}){255}){255})", REG_EXTENDED, REG_ESPACE);

	/* Pathological ReDoS patterns must finish linearly without hanging. */
	char a200[201], a25[26];
	memset(a200, 'a', 200); a200[200] = 0;
	memset(a25, 'a', 25); a25[25] = 0;
	expect_status("(a*)*b", REG_EXTENDED, a200, 0, REG_NOMATCH);
	expect_status("(a|aa)*c", REG_EXTENDED, a200, 0, REG_NOMATCH);
	expect_status("([a-z]+)+!", REG_EXTENDED, a200, 0, REG_NOMATCH);
	{ const regoff_t e[] = {0, 25, 0, 0}; expect_match("(a?){25}a{25}", REG_EXTENDED, a25, 0, 2, e); }
	{ const regoff_t e[] = {0, 200, 199, 200}; expect_match("(a+c|a)*", REG_EXTENDED, a200, 0, 2, e); }

	/* Bounded BRE multi-backref ReDoS must return REG_NOMATCH or REG_ESPACE promptly. */
	{
		char a40[41];
		memset(a40, 'a', 40); a40[40] = 0;
		regex_t re;
		if (regcomp(&re, "\\(a*\\)\\(a*\\)\\(a*\\)\\1\\2\\3b", 0) != 0) return 1;
		int rc = regexec(&re, a40, 0, NULL, 0);
		regfree(&re);
		if (rc != REG_NOMATCH && rc != REG_ESPACE) return 1;
	}

	puts("posix-regex-semantics ok");
	return 0;
}
