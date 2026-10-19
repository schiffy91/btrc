/* Two translation units of one program each include the Windows overlay's
   <regex.h>, <fnmatch.h> and <glob.h> (as two --module-units outputs do):
   each compiles its own internal copy of the engine, they link without
   clashing, and a regex_t one unit compiles the other can run and free. */
#include <fnmatch.h>
#include <glob.h>
#include <regex.h>
#include <stdio.h>

int overlay_helper_compile(regex_t *compiled, const char *pattern);
int overlay_helper_match(const char *pattern, const char *text);

int main(void)
{
	regex_t compiled;
	int compiled_status = overlay_helper_compile(&compiled, "b+");
	regmatch_t match[1];
	int matched = compiled_status == 0 && regexec(&compiled, "abbbc", 1, match, 0) == 0;
	if (compiled_status == 0) regfree(&compiled);
	int helper = overlay_helper_match("*.c", "unit.c");
	glob_t found;
	int globbed = glob("no-such-directory-*/x", 0, NULL, &found);
	printf("posix-overlay units regex=%d span=%d-%d fnmatch=%d glob=%d\n", matched, matched ? (int)match[0].rm_so : -1,
		matched ? (int)match[0].rm_eo : -1, helper, globbed == GLOB_NOMATCH);
	return matched && helper && globbed == GLOB_NOMATCH ? 0 : 1;
}
