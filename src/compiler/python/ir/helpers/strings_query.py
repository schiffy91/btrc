"""String query helpers — search, test, and predicate functions."""

from .core import HelperDef

STRING_QUERY = {
    "__btrc_charAt": HelperDef(
        c_source=(
            "static inline char __btrc_charAt(const char* s, int idx) {\n"
            "    if (!s) { fprintf(stderr, \"String index on NULL\\n\"); exit(1); }\n"
            "    int len = (int)strlen(s);\n"
            '    if (idx < 0 || idx >= len) { fprintf(stderr, "String index out of bounds: %d (length %d)\\n", idx, len); exit(1); }\n'
            "    return s[idx];\n"
            "}"
        ),
    ),
    "__btrc_indexOf": HelperDef(
        c_source=(
            "static inline int __btrc_indexOf(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return -1;\n"
            "    char* p = strstr(s, sub);\n"
            "    return p ? (int)(p - s) : -1;\n"
            "}"
        ),
    ),
    "__btrc_lastIndexOf": HelperDef(
        c_source=(
            "static inline int __btrc_lastIndexOf(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return -1;\n"
            "    int slen = (int)strlen(s);\n"
            "    int sublen = (int)strlen(sub);\n"
            "    if (sublen == 0) return slen;\n"
            "    for (int i = slen - sublen; i >= 0; i--) {\n"
            "        if (strncmp(s + i, sub, sublen) == 0) return i;\n"
            "    }\n"
            "    return -1;\n"
            "}"
        ),
    ),
    "__btrc_isEmpty": HelperDef(
        c_source=(
            "static inline bool __btrc_isEmpty(const char* s) {\n"
            "    if (!s) return true;\n"
            "    return s[0] == '\\0';\n"
            "}"
        ),
    ),
    "__btrc_startsWith": HelperDef(
        c_source=(
            "static inline bool __btrc_startsWith(const char* s, const char* prefix) {\n"
            "    if (!s || !prefix) return false;\n"
            "    return strncmp(s, prefix, strlen(prefix)) == 0;\n"
            "}"
        ),
    ),
    "__btrc_endsWith": HelperDef(
        c_source=(
            "static inline bool __btrc_endsWith(const char* s, const char* suffix) {\n"
            "    if (!s || !suffix) return false;\n"
            "    int slen = (int)strlen(s);\n"
            "    int suflen = (int)strlen(suffix);\n"
            "    if (suflen > slen) return false;\n"
            "    return strcmp(s + slen - suflen, suffix) == 0;\n"
            "}"
        ),
    ),
    "__btrc_strContains": HelperDef(
        c_source=(
            "static inline bool __btrc_strContains(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return false;\n"
            "    return strstr(s, sub) != NULL;\n"
            "}"
        ),
    ),
    "__btrc_count": HelperDef(
        c_source=(
            "static inline int __btrc_count(const char* s, const char* sub) {\n"
            "    if (!s || !sub) return 0;\n"
            "    int count = 0;\n"
            "    int sublen = (int)strlen(sub);\n"
            "    if (sublen == 0) return 0;\n"
            "    const char* p = s;\n"
            "    while ((p = strstr(p, sub)) != NULL) { count++; p += sublen; }\n"
            "    return count;\n"
            "}"
        ),
    ),
    "__btrc_find": HelperDef(
        c_source=(
            "static inline int __btrc_find(const char* s, const char* sub, int start) {\n"
            "    if (!s || !sub) return -1;\n"
            "    int len = (int)strlen(s);\n"
            "    if (start < 0 || start >= len) return -1;\n"
            "    const char* found = strstr(s + start, sub);\n"
            "    if (!found) return -1;\n"
            "    return (int)(found - s);\n"
            "}"
        ),
    ),
    "__btrc_isDigitStr": HelperDef(
        c_source=(
            "static inline bool __btrc_isDigitStr(const char* s) {\n"
            "    if (!*s) return false;\n"
            "    for (; *s; s++) if (!isdigit((unsigned char)*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isAlphaStr": HelperDef(
        c_source=(
            "static inline bool __btrc_isAlphaStr(const char* s) {\n"
            "    if (!*s) return false;\n"
            "    for (; *s; s++) if (!isalpha((unsigned char)*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isBlank": HelperDef(
        c_source=(
            "static inline bool __btrc_isBlank(const char* s) {\n"
            "    for (; *s; s++) if (!isspace((unsigned char)*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isUpper": HelperDef(
        c_source=(
            "static inline bool __btrc_isUpper(const char* s) {\n"
            "    if (*s == '\\0') return false;\n"
            "    for (; *s; s++) if (!isupper((unsigned char)*s) && !isspace((unsigned char)*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isLower": HelperDef(
        c_source=(
            "static inline bool __btrc_isLower(const char* s) {\n"
            "    if (*s == '\\0') return false;\n"
            "    for (; *s; s++) if (!islower((unsigned char)*s) && !isspace((unsigned char)*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_isAlnumStr": HelperDef(
        c_source=(
            "static inline bool __btrc_isAlnumStr(const char* s) {\n"
            "    if (*s == '\\0') return false;\n"
            "    for (; *s; s++) if (!isalnum((unsigned char)*s)) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_utf8_charlen": HelperDef(
        c_source=(
            "static inline int __btrc_utf8_charlen(const char* s) {\n"
            "    int count = 0;\n"
            "    while (*s) {\n"
            "        if ((*s & 0xC0) != 0x80) count++;\n"
            "        s++;\n"
            "    }\n"
            "    return count;\n"
            "}"
        ),
    ),
    "__btrc_charLen": HelperDef(
        c_source=(
            "static inline int __btrc_charLen(const char* s) {\n"
            "    int count = 0;\n"
            "    for (; *s; s++) { if ((*s & 0xC0) != 0x80) count++; }\n"
            "    return count;\n"
            "}"
        ),
    ),
}
