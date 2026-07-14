"""String search, test, predicate, and UTF-8 query helpers."""

from .core import HelperDef

_LENGTH = ["__btrc_string_length"]

STRING_QUERY = {
    "__btrc_charAt": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline char __btrc_charAt(const char* s, int idx) {\n"
            '    if (!s) { fprintf(stderr, "String index on NULL\\n"); exit(1); }\n'
            "    int len = __btrc_string_length(s);\n"
            '    if (idx < 0 || idx >= len) { fprintf(stderr, "String index out of bounds: %d (length %d)\\n", idx, len); exit(1); }\n'
            "    return s[idx];\n"
            "}"
        ),
    ),
    "__btrc_indexOf": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline int __btrc_indexOf(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return -1;\n"
            "    (void)__btrc_string_length(s);\n"
            "    (void)__btrc_string_length(sub);\n"
            "    const char* found = strstr(s, sub);\n"
            "    return found ? (int)(found - s) : -1;\n"
            "}"
        ),
    ),
    "__btrc_lastIndexOf": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline int __btrc_lastIndexOf(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return -1;\n"
            "    int slen = __btrc_string_length(s);\n"
            "    int sublen = __btrc_string_length(sub);\n"
            "    if (sublen == 0) return slen;\n"
            "    for (int i = slen - sublen; i >= 0; i--) {\n"
            "        if (memcmp(s + i, sub, (size_t)sublen) == 0) return i;\n"
            "    }\n"
            "    return -1;\n"
            "}"
        ),
    ),
    "__btrc_isEmpty": HelperDef(
        c_source=("static inline bool __btrc_isEmpty(const char* s) {\n    return !s || s[0] == '\\0';\n}"),
    ),
    "__btrc_startsWith": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline bool __btrc_startsWith(const char* s, const char* prefix) {\n"
            "    if (!s || !prefix) return false;\n"
            "    int slen = __btrc_string_length(s);\n"
            "    int prefix_len = __btrc_string_length(prefix);\n"
            "    return prefix_len <= slen\n"
            "        && memcmp(s, prefix, (size_t)prefix_len) == 0;\n"
            "}"
        ),
    ),
    "__btrc_endsWith": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline bool __btrc_endsWith(const char* s, const char* suffix) {\n"
            "    if (!s || !suffix) return false;\n"
            "    int slen = __btrc_string_length(s);\n"
            "    int suffix_len = __btrc_string_length(suffix);\n"
            "    return suffix_len <= slen\n"
            "        && memcmp(s + slen - suffix_len, suffix, (size_t)suffix_len) == 0;\n"
            "}"
        ),
    ),
    "__btrc_strContains": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline bool __btrc_strContains(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return false;\n"
            "    (void)__btrc_string_length(s);\n"
            "    (void)__btrc_string_length(sub);\n"
            "    return strstr(s, sub) != NULL;\n"
            "}"
        ),
    ),
    "__btrc_count": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline int __btrc_count(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return 0;\n"
            "    (void)__btrc_string_length(s);\n"
            "    int sublen = __btrc_string_length(sub);\n"
            "    if (sublen == 0) return 0;\n"
            "    int count = 0;\n"
            "    const char* cursor = s;\n"
            "    while ((cursor = strstr(cursor, sub)) != NULL) {\n"
            "        count++; cursor += sublen;\n"
            "    }\n"
            "    return count;\n"
            "}"
        ),
    ),
    "__btrc_find": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline int __btrc_find(const char* s, const char* sub, int start) {\n"
            "    if (!s || !sub) return -1;\n"
            "    int len = __btrc_string_length(s);\n"
            "    int sublen = __btrc_string_length(sub);\n"
            "    if (start < 0) start = 0;\n"
            "    if (start > len) return -1;\n"
            "    if (sublen == 0) return start;\n"
            "    const char* found = strstr(s + start, sub);\n"
            "    return found ? (int)(found - s) : -1;\n"
            "}"
        ),
    ),
    "__btrc_isDigitStr": HelperDef(
        c_source=(
            "static inline bool __btrc_isDigitStr(const char* s) {\n"
            "    if (!s || !*s) return false;\n"
            "    for (; *s; s++) if (*s < '0' || *s > '9') return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isAlphaStr": HelperDef(
        c_source=(
            "static inline bool __btrc_isAlphaStr(const char* s) {\n"
            "    if (!s || !*s) return false;\n"
            "    for (; *s; s++) {\n"
            "        unsigned char byte = (unsigned char)*s;\n"
            "        if (!((byte >= 'A' && byte <= 'Z')\n"
            "                || (byte >= 'a' && byte <= 'z'))) return false;\n"
            "    }\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isBlank": HelperDef(
        depends_on=["__btrc_ascii_space"],
        c_source=(
            "static inline bool __btrc_isBlank(const char* s) {\n"
            "    if (!s) return true;\n"
            "    for (; *s; s++) if (!__btrc_ascii_space(*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isUpper": HelperDef(
        depends_on=["__btrc_ascii_space"],
        c_source=(
            "static inline bool __btrc_isUpper(const char* s) {\n"
            "    if (!s || *s == '\\0') return false;\n"
            "    for (; *s; s++) {\n"
            "        unsigned char byte = (unsigned char)*s;\n"
            "        if (!(byte >= 'A' && byte <= 'Z') && !__btrc_ascii_space(*s))\n"
            "            return false;\n"
            "    }\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isLower": HelperDef(
        depends_on=["__btrc_ascii_space"],
        c_source=(
            "static inline bool __btrc_isLower(const char* s) {\n"
            "    if (!s || *s == '\\0') return false;\n"
            "    for (; *s; s++) {\n"
            "        unsigned char byte = (unsigned char)*s;\n"
            "        if (!(byte >= 'a' && byte <= 'z') && !__btrc_ascii_space(*s))\n"
            "            return false;\n"
            "    }\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isAlnumStr": HelperDef(
        c_source=(
            "static inline bool __btrc_isAlnumStr(const char* s) {\n"
            "    if (!s || *s == '\\0') return false;\n"
            "    for (; *s; s++) {\n"
            "        unsigned char byte = (unsigned char)*s;\n"
            "        if (!((byte >= '0' && byte <= '9')\n"
            "                || (byte >= 'A' && byte <= 'Z')\n"
            "                || (byte >= 'a' && byte <= 'z'))) return false;\n"
            "    }\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_utf8_charlen": HelperDef(
        depends_on=_LENGTH,
        c_source=(
            "static inline int __btrc_utf8_charlen(const char* s) {\n"
            "    if (!s) return 0;\n"
            "    int length = __btrc_string_length(s);\n"
            "    int count = 0;\n"
            "    int index = 0;\n"
            "    while (index < length) {\n"
            "        int remaining = length - index;\n"
            "        unsigned char c0 = (unsigned char)s[index];\n"
            "        unsigned char c1 = remaining > 1 ? (unsigned char)s[index + 1] : 0;\n"
            "        unsigned char c2 = remaining > 2 ? (unsigned char)s[index + 2] : 0;\n"
            "        unsigned char c3 = remaining > 3 ? (unsigned char)s[index + 3] : 0;\n"
            "        int advance = 1;\n"
            "        if (c0 >= 0xC2 && c0 <= 0xDF\n"
            "                && c1 >= 0x80 && c1 <= 0xBF) advance = 2;\n"
            "        else if (((c0 == 0xE0 && c1 >= 0xA0 && c1 <= 0xBF)\n"
            "                    || (c0 >= 0xE1 && c0 <= 0xEC && c1 >= 0x80 && c1 <= 0xBF)\n"
            "                    || (c0 == 0xED && c1 >= 0x80 && c1 <= 0x9F)\n"
            "                    || (c0 >= 0xEE && c0 <= 0xEF && c1 >= 0x80 && c1 <= 0xBF))\n"
            "                && c2 >= 0x80 && c2 <= 0xBF) advance = 3;\n"
            "        else if (((c0 == 0xF0 && c1 >= 0x90 && c1 <= 0xBF)\n"
            "                    || (c0 >= 0xF1 && c0 <= 0xF3 && c1 >= 0x80 && c1 <= 0xBF)\n"
            "                    || (c0 == 0xF4 && c1 >= 0x80 && c1 <= 0x8F))\n"
            "                && c2 >= 0x80 && c2 <= 0xBF\n"
            "                && c3 >= 0x80 && c3 <= 0xBF) advance = 4;\n"
            "        index += advance;\n"
            "        count++;\n"
            "    }\n"
            "    return count;\n"
            "}"
        ),
    ),
    "__btrc_charLen": HelperDef(
        depends_on=["__btrc_utf8_charlen"],
        c_source=("static inline int __btrc_charLen(const char* s) {\n    return __btrc_utf8_charlen(s);\n}"),
    ),
}
