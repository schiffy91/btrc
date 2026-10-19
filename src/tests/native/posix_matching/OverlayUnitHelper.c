/* The second unit of OverlayUnitMain.c's program. */
#include <fnmatch.h>
#include <glob.h>
#include <regex.h>

int overlay_helper_compile(regex_t *compiled, const char *pattern);
int overlay_helper_match(const char *pattern, const char *text);

int overlay_helper_compile(regex_t *compiled, const char *pattern)
{
	return regcomp(compiled, pattern, REG_EXTENDED);
}

int overlay_helper_match(const char *pattern, const char *text)
{
	return fnmatch(pattern, text, FNM_PATHNAME) == 0;
}
