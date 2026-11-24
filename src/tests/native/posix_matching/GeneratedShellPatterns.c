/* Generated shell patterns and paths for host-libc / Windows differential
   testing. The stream has a fixed order and one record per public API call. */
#include <fnmatch.h>
#include <stdio.h>

int main(void)
{
	static const char *const parts[] = {"", "x", "A", "?", "*", ".", "/", "[!b]", "[a-c]", "[[:alnum:]]", "\\*"};
	static const char *const subjects[] = {"", "x", "a", "A", "ab", ".a", "*", "x/a", "/.a", "/x", "a/A", "123", "é"};
	for (size_t i = 0; i < sizeof parts / sizeof *parts; ++i)
	for (size_t j = 0; j < sizeof parts / sizeof *parts; ++j)
	for (size_t k = 0; k < sizeof parts / sizeof *parts; ++k) {
		char pattern[64];
		snprintf(pattern, sizeof pattern, "%s%s%s", parts[i], parts[j], parts[k]);
		for (int mask = 0; mask < 8; ++mask) {
			int flags = ((mask & 1) ? FNM_PATHNAME : 0) | ((mask & 2) ? FNM_NOESCAPE : 0) |
			            ((mask & 4) ? FNM_PERIOD : 0);
			for (size_t s = 0; s < sizeof subjects / sizeof *subjects; ++s)
				putchar(fnmatch(pattern, subjects[s], flags) == 0 ? '+' : '-');
		}
		putchar('\n');
	}
	return 0;
}
