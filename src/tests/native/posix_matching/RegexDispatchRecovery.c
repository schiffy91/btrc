/* The flat matcher must preserve a result if its per-call working storage
   is unavailable. Fail one allocation and keep the compiled object alive. */
#include <stdint.h>
#include <stdlib.h>

static int fail_next, failures;

static void *test_malloc(size_t bytes)
{
	if (!fail_next) return malloc(bytes);
	fail_next = 0;
	++failures;
	return NULL;
}

#define malloc test_malloc
#include <regex.h>
#undef malloc

int main(void)
{
	char pattern[] = "[a-z]+[0-9]{2}|abc";
	regex_t re;
	if (regcomp(&re, pattern, REG_EXTENDED) || ((uintptr_t)re.__opaque & 3u) != 2) return 1;
	pattern[0] = 0;
	fail_next = 1;
	for (int run = 0; run < 2; ++run) {
		regmatch_t m[2];
		if (regexec(&re, "!!abc12zz", 2, m, 0) || m[0].rm_so != 2 || m[0].rm_eo != 7 ||
		    m[1].rm_so != -1 || m[1].rm_eo != -1) return 1;
	}
	regfree(&re);
	if (regcomp(&re, "([A-Z]{3})([0-9]{2})", REG_EXTENDED | REG_ICASE)) return 1;
	fail_next = 1;
	regmatch_t m[4];
	if (regexec(&re, "!!abc12zz", 4, m, 0) || m[0].rm_so != 2 || m[0].rm_eo != 7 ||
	    m[1].rm_so != 2 || m[1].rm_eo != 5 || m[2].rm_so != 5 || m[2].rm_eo != 7 ||
	    m[3].rm_so != -1 || m[3].rm_eo != -1) return 1;
	regfree(&re);
	return failures != 2;
}
