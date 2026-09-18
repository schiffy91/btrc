/* fontconfig resolves the system UI face for the Linux GUI provider. The
 * out-parameter query keeps FcChar8 pointer plumbing on the C side. */
#include <fontconfig/fontconfig.h>
#include <stdlib.h>
#include <string.h>

/* Returns a malloc'd file path for the best match, or NULL. */
static inline char* btrcFontconfigMatchFile(const char* family, int weight) {
	if (!FcInit()) { return NULL; }
	FcPattern* pattern = FcNameParse((const FcChar8*)family);
	if (pattern == NULL) { return NULL; }
	FcPatternAddInteger(pattern, FC_WEIGHT, weight);
	FcConfigSubstitute(NULL, pattern, FcMatchPattern);
	FcDefaultSubstitute(pattern);
	FcResult result = FcResultNoMatch;
	FcPattern* match = FcFontMatch(NULL, pattern, &result);
	FcPatternDestroy(pattern);
	if (match == NULL) { return NULL; }
	FcChar8* file = NULL;
	char* copy = NULL;
	if (FcPatternGetString(match, FC_FILE, 0, &file) == FcResultMatch && file != NULL) {
		size_t length = strlen((const char*)file);
		copy = (char*)malloc(length + 1);
		if (copy != NULL) { memcpy(copy, file, length + 1); }
	}
	FcPatternDestroy(match);
	return copy;
}

static inline void btrcFontconfigFree(char* path) { free(path); }
