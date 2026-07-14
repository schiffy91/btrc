"""String slicing, replacement, case, and sequence transformations."""

from .core import HelperDef
from .strings_common import NULL_RET_EMPTY

_ALLOC = ["__btrc_string_length", "__btrc_string_alloc"]

STRING_TRANSFORM = {
    "__btrc_substring": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_substring(const char* s, int start, int len) {\n"
            + NULL_RET_EMPTY
            + "    int slen = __btrc_string_length(s);\n"
            "    if (start < 0) start = 0;\n"
            "    if (start > slen) start = slen;\n"
            "    if (len < 0) len = 0;\n"
            "    if (len > slen - start) len = slen - start;\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    memcpy(result, s + start, (size_t)len);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_trim": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_space"],
        c_source=(
            "static inline char* __btrc_trim(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int slen = __btrc_string_length(s);\n"
            "    int start = 0;\n"
            "    while (start < slen && __btrc_ascii_space(s[start])) start++;\n"
            "    int end = slen;\n"
            "    while (end > start && __btrc_ascii_space(s[end - 1])) end--;\n"
            "    int length = end - start;\n"
            "    char* result = __btrc_string_alloc(length);\n"
            "    memcpy(result, s + start, (size_t)length);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_toUpper": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_upper"],
        c_source=(
            "static inline char* __btrc_toUpper(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    for (int i = 0; i < len; i++) result[i] = __btrc_ascii_upper(s[i]);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_toLower": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_lower"],
        c_source=(
            "static inline char* __btrc_toLower(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    for (int i = 0; i < len; i++) result[i] = __btrc_ascii_lower(s[i]);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_replace": HelperDef(
        depends_on=[*_ALLOC, "__btrc_strdup"],
        c_source=(
            "static inline char* __btrc_replace(const char* s, const char* old, const char* rep) {\n"
            + NULL_RET_EMPTY
            + "    if (!old || !old[0]) return __btrc_strdup(s);\n"
            '    if (!rep) rep = "";\n'
            "    int slen = __btrc_string_length(s);\n"
            "    int oldlen = __btrc_string_length(old);\n"
            "    int replen = __btrc_string_length(rep);\n"
            "    int matches = 0;\n"
            "    const char* scan = s;\n"
            "    while ((scan = strstr(scan, old)) != NULL) { matches++; scan += oldlen; }\n"
            "    long long total = (long long)slen\n"
            "        + (long long)matches * ((long long)replen - (long long)oldlen);\n"
            "    if (total < 0 || total > INT_MAX) {\n"
            '        fprintf(stderr, "btrc: string replace overflow\\n"); exit(1);\n'
            "    }\n"
            "    char* result = __btrc_string_alloc((int)total);\n"
            "    const char* input = s;\n"
            "    char* output = result;\n"
            "    const char* found;\n"
            "    while ((found = strstr(input, old)) != NULL) {\n"
            "        size_t prefix = (size_t)(found - input);\n"
            "        memcpy(output, input, prefix); output += prefix;\n"
            "        memcpy(output, rep, (size_t)replen); output += replen;\n"
            "        input = found + oldlen;\n"
            "    }\n"
            "    memcpy(output, input, strlen(input));\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_split": HelperDef(
        depends_on=["__btrc_safe_realloc", *_ALLOC],
        c_source=(
            "static inline char** __btrc_split(const char* s, const char* delim) {\n"
            "    if (!s || !delim) { char** r = (char**)__btrc_safe_realloc(NULL, sizeof(char*)); r[0] = NULL; return r; }\n"
            "    int slen = __btrc_string_length(s);\n"
            "    int dlen = __btrc_string_length(delim);\n"
            '    if (dlen == 0) { fprintf(stderr, "Empty delimiter in split()\\n"); exit(1); }\n'
            "    int cap = 8;\n"
            "    char** result = (char**)__btrc_safe_realloc(NULL, sizeof(char*) * (size_t)cap);\n"
            "    int count = 0;\n"
            "    const char* p = s;\n"
            "    for (;;) {\n"
            "        const char* found = strstr(p, delim);\n"
            "        int offset = (int)(p - s);\n"
            "        int seglen = found ? (int)(found - p) : slen - offset;\n"
            '        if (count > INT_MAX - 2) { fprintf(stderr, "btrc: split result overflow\\n"); exit(1); }\n'
            "        if (count + 2 > cap) {\n"
            "            if (cap > INT_MAX / 2\n"
            "                    || (size_t)(cap * 2) > SIZE_MAX / sizeof(char*)) {\n"
            '                fprintf(stderr, "btrc: split result overflow\\n"); exit(1);\n'
            "            }\n"
            "            cap *= 2;\n"
            "            result = (char**)__btrc_safe_realloc(\n"
            "                result, sizeof(char*) * (size_t)cap);\n"
            "        }\n"
            "        result[count] = __btrc_string_alloc(seglen);\n"
            "        memcpy(result[count], p, (size_t)seglen);\n"
            "        count++;\n"
            "        if (!found) break;\n"
            "        p = found + dlen;\n"
            "    }\n"
            "    result[count] = NULL;\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_repeat": HelperDef(
        depends_on=["__btrc_safe_realloc", "__btrc_string_length", "__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_repeat(const char* s, int count) {\n"
            + NULL_RET_EMPTY
            + "    if (count <= 0) { char* r = (char*)__btrc_safe_realloc(NULL, 1); r[0] = '\\0'; return r; }\n"
            "    int slen = __btrc_string_length(s);\n"
            "    if (slen > 0 && count > (INT_MAX - 1) / slen) {\n"
            '        fprintf(stderr, "btrc: string repeat overflow\\n"); exit(1);\n'
            "    }\n"
            "    int total = slen * count;\n"
            "    char* result = (char*)__btrc_safe_realloc(NULL, (size_t)total + 1);\n"
            "    for (int i = 0; i < count; i++)\n"
            "        memcpy(result + (size_t)i * (size_t)slen, s, (size_t)slen);\n"
            "    result[total] = '\\0';\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_reverse": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_reverse(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    for (int i = 0; i < len; i++) result[i] = s[len - 1 - i];\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_removePrefix": HelperDef(
        depends_on=[*_ALLOC, "__btrc_strdup"],
        c_source=(
            "static inline char* __btrc_removePrefix(const char* s, const char* prefix) {\n"
            + NULL_RET_EMPTY
            + "    if (!prefix) return __btrc_strdup(s);\n"
            "    int slen = __btrc_string_length(s);\n"
            "    int plen = __btrc_string_length(prefix);\n"
            "    if (plen <= slen && memcmp(s, prefix, (size_t)plen) == 0) {\n"
            "        int length = slen - plen;\n"
            "        char* result = __btrc_string_alloc(length);\n"
            "        memcpy(result, s + plen, (size_t)length);\n"
            "        return result;\n"
            "    }\n"
            "    return __btrc_strdup(s);\n"
            "}"
        ),
    ),
    "__btrc_removeSuffix": HelperDef(
        depends_on=[*_ALLOC, "__btrc_strdup"],
        c_source=(
            "static inline char* __btrc_removeSuffix(const char* s, const char* suffix) {\n"
            + NULL_RET_EMPTY
            + "    if (!suffix) return __btrc_strdup(s);\n"
            "    int slen = __btrc_string_length(s);\n"
            "    int suflen = __btrc_string_length(suffix);\n"
            "    if (suflen <= slen\n"
            "            && memcmp(s + slen - suflen, suffix, (size_t)suflen) == 0) {\n"
            "        int length = slen - suflen;\n"
            "        char* result = __btrc_string_alloc(length);\n"
            "        memcpy(result, s, (size_t)length);\n"
            "        return result;\n"
            "    }\n"
            "    return __btrc_strdup(s);\n"
            "}"
        ),
    ),
    "__btrc_capitalize": HelperDef(
        depends_on=[
            *_ALLOC,
            "__btrc_ascii_lower",
            "__btrc_ascii_space",
            "__btrc_ascii_upper",
        ],
        c_source=(
            "static inline char* __btrc_capitalize(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    for (int i = 0; i < len; i++) result[i] = __btrc_ascii_lower(s[i]);\n"
            "    if (len > 0) result[0] = __btrc_ascii_upper(result[0]);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_title": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_lower", "__btrc_ascii_upper"],
        c_source=(
            "static inline char* __btrc_title(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    int cap_next = 1;\n"
            "    for (int i = 0; i < len; i++) {\n"
            "        if (__btrc_ascii_space(s[i])) { result[i] = s[i]; cap_next = 1; }\n"
            "        else if (cap_next) { result[i] = __btrc_ascii_upper(s[i]); cap_next = 0; }\n"
            "        else { result[i] = __btrc_ascii_lower(s[i]); }\n"
            "    }\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_swapCase": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_lower", "__btrc_ascii_upper"],
        c_source=(
            "static inline char* __btrc_swapCase(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    for (int i = 0; i < len; i++) {\n"
            "        unsigned char byte = (unsigned char)s[i];\n"
            "        if (byte >= 'A' && byte <= 'Z') result[i] = __btrc_ascii_lower(s[i]);\n"
            "        else if (byte >= 'a' && byte <= 'z') result[i] = __btrc_ascii_upper(s[i]);\n"
            "        else result[i] = s[i];\n"
            "    }\n"
            "    return result;\n"
            "}"
        ),
    ),
}
