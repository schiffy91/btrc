/* Two translation units of one program each include the Windows overlay's
   <regex.h>, <fnmatch.h> and <glob.h> (as two --module-units outputs do):
   each compiles its own internal copy of the engine, they link without
   clashing, and a regex_t one unit compiles the other can run and free. */
#include <fnmatch.h>
#include <glob.h>
#include <regex.h>
#include <stdint.h>
#include <stdio.h>

int overlay_helper_compile(regex_t *compiled, const char *pattern);
int overlay_helper_match(const char *pattern, const char *text);

int main(void)
{
	regex_t compiled;
	if (overlay_helper_compile(&compiled, "b+") != 0 || !((uintptr_t)compiled.__opaque & 1u)) return 1;
	regmatch_t match[1];
	int matched = regexec(&compiled, "abbbc", 1, match, 0) == 0;
	regfree(&compiled);
	regmatch_t span[1];
	if (overlay_helper_compile(&compiled, "[a-z]{2,3}") != 0 || !((uintptr_t)compiled.__opaque & 1u)) return 1;
	if (regexec(&compiled, "5x1abcd", 1, span, 0) || span[0].rm_so != 3 || span[0].rm_eo != 6) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "^ab$") != 0 || !((uintptr_t)compiled.__opaque & 1u)) return 1;
	if (regexec(&compiled, "ab", 1, span, REG_NOTBOL) != REG_NOMATCH ||
	    regexec(&compiled, "ab", 1, span, REG_NOTEOL) != REG_NOMATCH) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "^[a-z]{1,3}$") != 0 || !((uintptr_t)compiled.__opaque & 1u)) return 1;
	if (regexec(&compiled, "aba", 1, span, 0) || span[0].rm_so != 0 || span[0].rm_eo != 3 ||
	    regexec(&compiled, "baba", 0, NULL, 0) != REG_NOMATCH) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "[a-z]+[0-9]{2}|abc") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 2) return 1;
	if (regexec(&compiled, "abc12zz", 1, span, 0) || span[0].rm_so != 0 || span[0].rm_eo != 5) return 1;
	regfree(&compiled);
	regmatch_t capture[4];
	if (overlay_helper_compile(&compiled, "(([a-c]+|xy))") != 0 || compiled.re_nsub != 2 ||
	    ((uintptr_t)compiled.__opaque & 3u) != 2 || regexec(&compiled, "!abcd", 4, capture, 0)) return 1;
	for (int g = 0; g < 3; ++g) if (capture[g].rm_so != 1 || capture[g].rm_eo != 4) return 1;
	if (capture[3].rm_so != -1 || capture[3].rm_eo != -1) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "[a-z]{2}([0-9]{3})/([A-Z])") != 0 || compiled.re_nsub != 2 ||
	    ((uintptr_t)compiled.__opaque & 3u) != 2 || regexec(&compiled, "!ab123/X", 4, capture, 0)) return 1;
	if (capture[0].rm_so != 1 || capture[0].rm_eo != 8 || capture[1].rm_so != 3 || capture[1].rm_eo != 6 ||
	    capture[2].rm_so != 7 || capture[2].rm_eo != 8 || capture[3].rm_so != -1) return 1;
	regfree(&compiled);
	if (regcomp(&compiled, "a+b", 0) || ((uintptr_t)compiled.__opaque & 3u) != 2 ||
	    regexec(&compiled, "!a+b", 1, span, 0) || span[0].rm_so != 1 || span[0].rm_eo != 4) return 1;
	regfree(&compiled);
	if (regcomp(&compiled, "(ab.)", REG_EXTENDED | REG_ICASE | REG_NEWLINE) || ((uintptr_t)compiled.__opaque & 3u) != 2 ||
	    regexec(&compiled, "AB\n", 2, capture, 0) != REG_NOMATCH || regexec(&compiled, "xAB!", 2, capture, 0) ||
	    capture[1].rm_so != 1 || capture[1].rm_eo != 4) return 1;
	regfree(&compiled);
	if (regcomp(&compiled, "([a-z]+)", REG_EXTENDED | REG_ICASE | REG_NOSUB) || compiled.re_nsub != 1 ||
	    ((uintptr_t)compiled.__opaque & 3u) != 2) return 1;
	capture[0] = (regmatch_t){17, 19};
	if (regexec(&compiled, "AB", 1, capture, 0) || capture[0].rm_so != 17 || capture[0].rm_eo != 19) return 1;
	regfree(&compiled);
	if (regcomp(&compiled, "\\(a\\|b\\)", 0) || ((uintptr_t)compiled.__opaque & 3u) != 2 ||
	    regexec(&compiled, "xby", 2, capture, 0) || capture[1].rm_so != 1 || capture[1].rm_eo != 2) return 1;
	regfree(&compiled);
	if (regcomp(&compiled, "\\x41", REG_EXTENDED | REG_ICASE) || ((uintptr_t)compiled.__opaque & 3u) != 2 ||
	    regexec(&compiled, "a", 1, span, 0) != REG_NOMATCH || regexec(&compiled, "A", 1, span, 0)) return 1;
	regfree(&compiled);
	if (regcomp(&compiled, "\\D", REG_EXTENDED | REG_NEWLINE) || ((uintptr_t)compiled.__opaque & 3u) != 2 ||
	    regexec(&compiled, "\n", 1, span, 0) != REG_NOMATCH || regexec(&compiled, "x", 1, span, 0)) return 1;
	regfree(&compiled);
	char literal[] = "ababaca";
	if (overlay_helper_compile(&compiled, literal) != 0 || !((uintptr_t)compiled.__opaque & 1u)) return 1;
	literal[0] = 'z';
	if (regexec(&compiled, "abababaca", 1, span, 0) || span[0].rm_so != 2 || span[0].rm_eo != 9) return 1;
	regfree(&compiled);
	char nested[] = "((a{2})?b)?";
	if (overlay_helper_compile(&compiled, nested) != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3 || compiled.re_nsub != 2) return 1;
	nested[2] = 'z';
	regmatch_t groups[3];
	if (regexec(&compiled, "ab", 3, groups, 0) || groups[0].rm_so != 0 || groups[0].rm_eo != 2 ||
	    groups[1].rm_so != 0 || groups[1].rm_eo != 2 || groups[2].rm_so != -1 || groups[2].rm_eo != -1) return 1;
	if (regexec(&compiled, "ab", 1, span, 0) || span[0].rm_so != 0 || span[0].rm_eo != 2) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((b{1,3}){2,3}|.x){0,2}") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	if (regexec(&compiled, "ab", 0, NULL, REG_NOTBOL | REG_NOTEOL) || regexec(&compiled, "ab", 1, span, 0) || span[0].rm_eo != 2) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((a{255})?b)?") != 0 || ((uintptr_t)compiled.__opaque & 3u)) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "([[:digit:]])+.{2,4}") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	if (regexec(&compiled, "1x12345", 3, groups, REG_NOTBOL) || groups[0].rm_so != 2 || groups[0].rm_eo != 7 ||
	    groups[1].rm_so != 4 || groups[1].rm_eo != 5 || groups[2].rm_so != -1 || groups[2].rm_eo != -1) return 1;
	if (regexec(&compiled, "abc", 0, NULL, 0) != REG_NOMATCH) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((((b){0,3})+|((.){2,4}))){2}") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	if (regexec(&compiled, "x", 1, span, 0) || span[0].rm_so != 0 || span[0].rm_eo != 1) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((a|ab)b+)") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	if (regexec(&compiled, "aabbb", 1, span, 0) || span[0].rm_so != 1 || span[0].rm_eo != 5 ||
	    regexec(&compiled, "aaaa", 0, NULL, 0) != REG_NOMATCH) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((a){2})") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	const btrc_win_pos_program *positions = (const btrc_win_pos_program *)((uintptr_t)compiled.__opaque - 3);
	if (btrc_win_pos_match(positions, "aaaa", 1, span) != btrc_win_pos_competing_starts ||
	    regexec(&compiled, "aaaa", 1, span, 0) || span[0].rm_so != 0 || span[0].rm_eo != 2) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "(((([abc]){0}|.)|(b){0}[[:space:]])){1,3}") != 0 ||
	    ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	if (regexec(&compiled, "abbba", 1, span, 0) || span[0].rm_so != 0 || span[0].rm_eo != 5) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((((ab){2,}){1,3}|a)){2,4}") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	positions = (const btrc_win_pos_program *)((uintptr_t)compiled.__opaque - 3);
	if (positions->edges <= 64 || btrc_win_pos_match(positions, "aab", 1, span) ||
	    span[0].rm_so != 0 || span[0].rm_eo != 3) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "((a|$)(.){0}(b)){2}") != 0 || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	if (regexec(&compiled, "aab", 1, span, REG_NOTEOL) || span[0].rm_so != 0 || span[0].rm_eo != 3) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "(([^ab]|(..){1,3}))+")) return 1;
	positions = (const btrc_win_pos_program *)((uintptr_t)compiled.__opaque - 3);
	if (((uintptr_t)compiled.__opaque & 3u) != 3 || positions->ranked_blocks.width != 2 ||
	    btrc_win_pos_match(positions, "abbba", 1, span) || span[0].rm_so != 1 || span[0].rm_eo != 5) return 1;
	if (btrc_win_rx_block_match(&positions->ranked_blocks, "abb!a", span) != btrc_win_pos_competing_starts) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "(((b)?){2})?([abc]){2,4}") || ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	positions = (const btrc_win_pos_program *)((uintptr_t)compiled.__opaque - 3);
	if (positions->optional_suffix.optional_prefix_limit != 2 || btrc_win_pos_match(positions, "abbba", 1, span) ||
	    span[0].rm_so != 1 || span[0].rm_eo != 5) return 1;
	regfree(&compiled);
	if (overlay_helper_compile(&compiled, "(\\B|(((a){0,3}|([^ab]){2})){2,4})") ||
	    ((uintptr_t)compiled.__opaque & 3u) != 3) return 1;
	positions = (const btrc_win_pos_program *)((uintptr_t)compiled.__opaque - 3);
	if (positions->boundary_blocks.width != 2 || btrc_win_pos_match(positions, "xxx", 1, span) ||
	    span[0].rm_so != 1 || span[0].rm_eo != 3 || btrc_win_pos_match(positions, "xxx", 0, NULL) ||
	    btrc_win_pos_match(positions, "x", 0, NULL) != REG_NOMATCH ||
	    btrc_win_pos_match(positions, "xxxaa", 1, span) != btrc_win_pos_competing_starts) return 1;
	regfree(&compiled);
	int helper = overlay_helper_match("*.c", "unit.c");
	glob_t found;
	int globbed = glob("no-such-directory-*/x", 0, NULL, &found);
	printf("posix-overlay units regex=%d span=%d-%d fnmatch=%d glob=%d\n", matched, matched ? (int)match[0].rm_so : -1,
		matched ? (int)match[0].rm_eo : -1, helper, globbed == GLOB_NOMATCH);
	return matched && helper && globbed == GLOB_NOMATCH ? 0 : 1;
}
