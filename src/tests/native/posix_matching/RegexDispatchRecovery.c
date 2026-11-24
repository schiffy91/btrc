/* Allocation failure during regexec must report REG_ESPACE cleanly without
   leaking memory or corrupting the compiled regex_t, so subsequent calls on
   the same compiled object still succeed. */
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
	/* Large NFA (>256 instructions) forces Pass-1 heap workspace allocation. */
	regex_t re;
	if (regcomp(&re, "(a|b){150}(c|d){150}", REG_EXTENDED) != 0) return 1;
	fail_next = 1;
	regmatch_t m[4];
	if (regexec(&re, "abc", 1, m, 0) != REG_ESPACE) return 1;
	if (regexec(&re, "abc", 1, m, 0) != REG_NOMATCH) return 1;
	regfree(&re);

	/* Pass-2 submatch extraction heap allocation failure leaves regex_t intact. */
	if (regcomp(&re, "([A-Z]{3})([0-9]{2})", REG_EXTENDED | REG_ICASE) != 0) return 1;
	fail_next = 1;
	int rc = regexec(&re, "!!abc12zz", 4, m, 0);
	if (rc != 0 && rc != REG_ESPACE) return 1;
	if (regexec(&re, "!!abc12zz", 4, m, 0) != 0 ||
	    m[0].rm_so != 2 || m[0].rm_eo != 7 ||
	    m[1].rm_so != 2 || m[1].rm_eo != 5 ||
	    m[2].rm_so != 5 || m[2].rm_eo != 7 ||
	    m[3].rm_so != -1 || m[3].rm_eo != -1) return 1;
	regfree(&re);

	/* Pass-3 backreference frontier allocation failure leaves regex_t intact. */
	if (regcomp(&re, "\\([a-z]\\+\\):\\1", 0) != 0) return 1;
	fail_next = 1;
	if (regexec(&re, "!ab:ab!", 2, m, 0) != REG_ESPACE) return 1;
	if (regexec(&re, "!ab:ab!", 2, m, 0) != 0 ||
	    m[0].rm_so != 1 || m[0].rm_eo != 6 ||
	    m[1].rm_so != 1 || m[1].rm_eo != 3) return 1;
	regfree(&re);

	return failures != 3;
}
