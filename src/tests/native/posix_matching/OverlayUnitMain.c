/* Two translation units of one program each include the Windows overlay's
   <regex.h>, <fnmatch.h> and <glob.h> (as two --module-units outputs do):
   each compiles its own internal copy of the first-party engine, they link
   without clashing, and a regex_t one unit compiles the other can run and free. */
#include <fnmatch.h>
#include <glob.h>
#include <regex.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int overlay_helper_compile(regex_t *compiled, const char *pattern);
int overlay_helper_match(const char *pattern, const char *text);

int main(void)
{
	regex_t compiled;
	regmatch_t match[1], span[1], capture[5];

	/* Fast-path single atom and anchored literal compiled in helper TU. */
	if (overlay_helper_compile(&compiled, "b+") != 0) return 1;
	int matched = regexec(&compiled, "abbbc", 1, match, 0) == 0;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "[a-z]{2,3}") != 0 ||
	    regexec(&compiled, "5x1abcd", 1, span, 0) != 0 ||
	    span[0].rm_so != 3 || span[0].rm_eo != 6) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "^ab$") != 0 ||
	    regexec(&compiled, "ab", 1, span, REG_NOTBOL) != REG_NOMATCH ||
	    regexec(&compiled, "ab", 1, span, REG_NOTEOL) != REG_NOMATCH) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "^[a-z]{1,3}$") != 0 ||
	    regexec(&compiled, "aba", 1, span, 0) != 0 || span[0].rm_so != 0 || span[0].rm_eo != 3 ||
	    regexec(&compiled, "baba", 0, NULL, 0) != REG_NOMATCH) return 1;
	regfree(&compiled);

	/* Literal KMP owns a copy of the pattern buffer. */
	char literal[] = "ababaca";
	if (overlay_helper_compile(&compiled, literal) != 0) return 1;
	literal[0] = 'z';
	if (regexec(&compiled, "abababaca", 1, span, 0) != 0 ||
	    span[0].rm_so != 2 || span[0].rm_eo != 9) return 1;
	regfree(&compiled);

	/* Alternation, groups and exact POSIX leftmost-longest submatches. */
	if (overlay_helper_compile(&compiled, "[a-z]+[0-9]{2}|abc") != 0 ||
	    regexec(&compiled, "abc12zz", 1, span, 0) != 0 ||
	    span[0].rm_so != 0 || span[0].rm_eo != 5) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "(([a-c]+|xy))") != 0 || compiled.re_nsub != 2 ||
	    regexec(&compiled, "!abcd", 4, capture, 0) != 0) return 1;
	for (int g = 0; g < 3; ++g)
		if (capture[g].rm_so != 1 || capture[g].rm_eo != 4) return 1;
	if (capture[3].rm_so != -1 || capture[3].rm_eo != -1) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "[a-z]{2}([0-9]{3})/([A-Z])") != 0 || compiled.re_nsub != 2 ||
	    regexec(&compiled, "!ab123/X", 4, capture, 0) != 0 ||
	    capture[0].rm_so != 1 || capture[0].rm_eo != 8 ||
	    capture[1].rm_so != 3 || capture[1].rm_eo != 6 ||
	    capture[2].rm_so != 7 || capture[2].rm_eo != 8 || capture[3].rm_so != -1) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "([a-z]+)-([0-9]+)") != 0 ||
	    regexec(&compiled, "!test-42.", 4, capture, 0) != 0 ||
	    capture[0].rm_so != 1 || capture[0].rm_eo != 8 ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 5 ||
	    capture[2].rm_so != 6 || capture[2].rm_eo != 8 || capture[3].rm_so != -1) return 1;
	regfree(&compiled);

	/* Exact POSIX nested intervals and leftmost-longest priority. */
	if (overlay_helper_compile(&compiled, "((a{2})?b)?") != 0 || compiled.re_nsub != 2 ||
	    regexec(&compiled, "ab", 3, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 0 ||
	    capture[1].rm_so != -1 || capture[2].rm_so != -1 ||
	    regexec(&compiled, "aab", 3, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 3 ||
	    capture[1].rm_so != 0 || capture[1].rm_eo != 3 ||
	    capture[2].rm_so != 0 || capture[2].rm_eo != 2) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "((b{1,3}){2,3}|.x){0,2}") != 0 ||
	    regexec(&compiled, "ab", 1, span, 0) != 0 ||
	    span[0].rm_so != 0 || span[0].rm_eo != 0) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "([[:digit:]])+.{2,4}") != 0 ||
	    regexec(&compiled, "1x12345", 3, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 5 ||
	    capture[1].rm_so != 0 || capture[1].rm_eo != 1 || capture[2].rm_so != -1) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "((..){1,3})+") != 0 ||
	    regexec(&compiled, "abcde", 3, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 4 ||
	    capture[1].rm_so != 0 || capture[1].rm_eo != 4 ||
	    capture[2].rm_so != 2 || capture[2].rm_eo != 4) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "(a|aa|aaa)*") != 0 ||
	    regexec(&compiled, "aaaa", 2, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 4 ||
	    capture[1].rm_so != 3 || capture[1].rm_eo != 4) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "((a|ab)(b|ab))*") != 0 ||
	    regexec(&compiled, "abab", 4, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 4 ||
	    capture[1].rm_so != 0 || capture[1].rm_eo != 4 ||
	    capture[2].rm_so != 0 || capture[2].rm_eo != 2 ||
	    capture[3].rm_so != 2 || capture[3].rm_eo != 4) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "((a{255})?b)?") != 0 ||
	    regexec(&compiled, "b", 1, span, 0) != 0 ||
	    span[0].rm_so != 0 || span[0].rm_eo != 1) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "(^)?a") != 0 ||
	    regexec(&compiled, "ba", 2, capture, 0) != 0 ||
	    capture[0].rm_so != 1 || capture[0].rm_eo != 2 || capture[1].rm_so != -1) return 1;
	regfree(&compiled);

	if (overlay_helper_compile(&compiled, "($|^)a") != 0 ||
	    regexec(&compiled, "a", 2, capture, 0) != 0 ||
	    capture[0].rm_so != 0 || capture[0].rm_eo != 1 ||
	    capture[1].rm_so != 0 || capture[1].rm_eo != 0) return 1;
	regfree(&compiled);

	/* Flags: REG_ICASE, REG_NEWLINE, REG_NOSUB, REG_NOTBOL, REG_NOTEOL. */
	if (regcomp(&compiled, "(ab.)", REG_EXTENDED | REG_ICASE | REG_NEWLINE) != 0 ||
	    regexec(&compiled, "AB\n", 2, capture, 0) != REG_NOMATCH ||
	    regexec(&compiled, "xAB!", 2, capture, 0) != 0 ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 4) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "([a-z]+)", REG_EXTENDED | REG_ICASE | REG_NOSUB) != 0 ||
	    compiled.re_nsub != 1) return 1;
	capture[0] = (regmatch_t){17, 19};
	if (regexec(&compiled, "AB", 1, capture, 0) != 0 ||
	    capture[0].rm_so != 17 || capture[0].rm_eo != 19) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "^ab$", REG_EXTENDED | REG_ICASE | REG_NEWLINE) != 0 ||
	    regexec(&compiled, "zz\nAb\n", 1, span, REG_NOTBOL | REG_NOTEOL) != 0 ||
	    span[0].rm_so != 3 || span[0].rm_eo != 5) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "((^a)|(b$))+", REG_EXTENDED | REG_NEWLINE) != 0 ||
	    regexec(&compiled, "x\na\nb\n", 1, span, REG_NOTBOL | REG_NOTEOL) != 0 ||
	    span[0].rm_so != 2 || span[0].rm_eo != 3) return 1;
	regfree(&compiled);

	/* Escapes, hex literals, word boundaries, collating elements, empty patterns. */
	if (regcomp(&compiled, "\\x41", REG_EXTENDED | REG_ICASE) != 0 ||
	    regexec(&compiled, "a", 1, span, 0) != REG_NOMATCH ||
	    regexec(&compiled, "A", 1, span, 0) != 0) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "\\D", REG_EXTENDED | REG_NEWLINE) != 0 ||
	    regexec(&compiled, "\n", 1, span, 0) != REG_NOMATCH ||
	    regexec(&compiled, "x", 1, span, 0) != 0) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "(\\bword\\b)", REG_EXTENDED) != 0 ||
	    regexec(&compiled, "-word!", 2, capture, 0) != 0 ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 5) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "[[.a.]-[.c.]]", REG_EXTENDED) != 0 ||
	    regexec(&compiled, "xb", 1, span, 0) != 0 || span[0].rm_so != 1 || span[0].rm_eo != 2) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "(())", REG_EXTENDED) != 0 || compiled.re_nsub != 2 ||
	    regexec(&compiled, "x", 4, capture, 0) != 0) return 1;
	for (int g = 0; g < 3; ++g)
		if (capture[g].rm_so != 0 || capture[g].rm_eo != 0) return 1;
	if (capture[3].rm_so != -1 || capture[3].rm_eo != -1) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "", 0) != 0 ||
	    regexec(&compiled, "", 1, span, REG_NOTBOL | REG_NOTEOL) != 0 ||
	    span[0].rm_so != 0 || span[0].rm_eo != 0) return 1;
	regfree(&compiled);

	/* BRE operators and backreferences \1..\9. */
	if (regcomp(&compiled, "a+b", 0) != 0 ||
	    regexec(&compiled, "!a+b", 1, span, 0) != 0 || span[0].rm_so != 1 || span[0].rm_eo != 4) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "\\(a\\|b\\)", 0) != 0 ||
	    regexec(&compiled, "xby", 2, capture, 0) != 0 ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 2) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "^\\([ab]\\{2\\}\\)\\1$", 0) != 0 ||
	    regexec(&compiled, "baba", 3, capture, 0) != 0 ||
	    capture[0].rm_eo != 4 || capture[1].rm_so != 0 || capture[1].rm_eo != 2 || capture[2].rm_so != -1 ||
	    regexec(&compiled, "baba", 0, NULL, REG_NOTBOL) != REG_NOMATCH) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "\\([a-z]\\+\\):\\1", REG_ICASE) != 0 ||
	    regexec(&compiled, "!Ab:Ab.", 2, capture, 0) != 0 ||
	    capture[0].rm_so != 1 || capture[0].rm_eo != 6 ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 3 ||
	    regexec(&compiled, "!Ab:ab.", 2, capture, 0) != 0 ||
	    capture[0].rm_so != 1 || capture[0].rm_eo != 6) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "\\(a*\\)b\\1", 0) != 0 ||
	    regexec(&compiled, "aaba", 2, capture, 0) != 0 ||
	    capture[0].rm_so != 1 || capture[0].rm_eo != 4 ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 2) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "\\(\\(a\\)\\|b\\)\\2", 0) != 0 ||
	    regexec(&compiled, "b", 1, span, 0) != REG_NOMATCH) return 1;
	regfree(&compiled);

	if (regcomp(&compiled, "\\(\\1\\)", 0) != REG_ESUBREG) return 1;

	/* Diagnostics via regerror. */
	char msg[32];
	if (regcomp(&compiled, "[", REG_EXTENDED) != REG_EBRACK) return 1;
	if (regerror(REG_EBRACK, &compiled, msg, sizeof msg) != 12 || strcmp(msg, "Missing ']'") != 0) return 1;

	int helper = overlay_helper_match("*.c", "unit.c");
	glob_t found;
	int globbed = glob("no-such-directory-*/x", 0, NULL, &found);
	printf("posix-overlay units regex=%d span=%d-%d fnmatch=%d glob=%d\n", matched, matched ? (int)match[0].rm_so : -1,
		matched ? (int)match[0].rm_eo : -1, helper, globbed == GLOB_NOMATCH);
	return matched && helper && globbed == GLOB_NOMATCH ? 0 : 1;
}
