"""String runtime helpers -- string manipulation helpers."""

from .core import HelperDef

STRING = {
    "__btrc_substring": HelperDef(
        c_source=(
            "static inline char* __btrc_substring(const char* s, int start, int len) {\n"
            "    int slen = (int)strlen(s);\n"
            "    if (start < 0) start = 0;\n"
            "    if (start > slen) start = slen;\n"
            "    if (start + len > slen) len = slen - start;\n"
            "    if (len < 0) len = 0;\n"
            "    char* result = (char*)malloc(len + 1);\n"
            "    strncpy(result, s + start, len);\n"
            "    result[len] = '\\0';\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_trim": HelperDef(
        c_source=(
            "static inline char* __btrc_trim(const char* s) {\n"
            "    while (*s && isspace((unsigned char)*s)) s++;\n"
            "    if (*s == '\\0') { char* r = (char*)malloc(1); r[0]='\\0'; return r; }\n"
            "    const char* end = s + strlen(s) - 1;\n"
            "    while (end > s && isspace((unsigned char)*end)) end--;\n"
            "    int len = (int)(end - s + 1);\n"
            "    char* result = (char*)malloc(len + 1);\n"
            "    strncpy(result, s, len);\n"
            "    result[len] = '\\0';\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_toUpper": HelperDef(
        c_source=(
            "static inline char* __btrc_toUpper(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    char* result = (char*)malloc(len + 1);\n"
            "    for (int i = 0; i < len; i++) result[i] = (char)toupper((unsigned char)s[i]);\n"
            "    result[len] = '\\0';\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_toLower": HelperDef(
        c_source=(
            "static inline char* __btrc_toLower(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    char* result = (char*)malloc(len + 1);\n"
            "    for (int i = 0; i < len; i++) result[i] = (char)tolower((unsigned char)s[i]);\n"
            "    result[len] = '\\0';\n"
            "    return result;\n"
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
    "__btrc_charAt": HelperDef(
        c_source=(
            "static inline char __btrc_charAt(const char* s, int idx) {\n"
            "    int len = (int)strlen(s);\n"
            '    if (idx < 0 || idx >= len) { fprintf(stderr, "String index out of bounds: %d (length %d)\\n", idx, len); exit(1); }\n'
            "    return s[idx];\n"
            "}"
        ),
    ),
    "__btrc_indexOf": HelperDef(
        c_source=(
            "static inline int __btrc_indexOf(const char* s, const char* sub) {\n"
            "    char* p = strstr(s, sub);\n"
            "    return p ? (int)(p - s) : -1;\n"
            "}"
        ),
    ),
    "__btrc_lastIndexOf": HelperDef(
        c_source=(
            "static inline int __btrc_lastIndexOf(const char* s, const char* sub) {\n"
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
    "__btrc_replace": HelperDef(
        c_source=(
            "static inline char* __btrc_replace(const char* s, const char* old, const char* rep) {\n"
            "    int slen = (int)strlen(s);\n"
            "    int oldlen = (int)strlen(old);\n"
            "    int replen = (int)strlen(rep);\n"
            "    if (oldlen == 0) return strdup(s);\n"
            "    int cap = slen * 2 + 1;\n"
            "    char* result = (char*)malloc(cap);\n"
            "    int rlen = 0, i = 0;\n"
            "    while (i < slen) {\n"
            "        if (i + oldlen <= slen && strncmp(s + i, old, oldlen) == 0) {\n"
            "            while (rlen + replen >= cap) { cap *= 2; result = (char*)realloc(result, cap); }\n"
            "            memcpy(result + rlen, rep, replen);\n"
            "            rlen += replen; i += oldlen;\n"
            "        } else {\n"
            "            if (rlen + 1 >= cap) { cap *= 2; result = (char*)realloc(result, cap); }\n"
            "            result[rlen++] = s[i++];\n"
            "        }\n"
            "    }\n"
            "    result[rlen] = '\\0';\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_split": HelperDef(
        c_source=(
            "static inline char** __btrc_split(const char* s, const char* delim) {\n"
            "    int dlen = (int)strlen(delim);\n"
            '    if (dlen == 0) { fprintf(stderr, "Empty delimiter in split()\\n"); exit(1); }\n'
            "    int cap = 8;\n"
            "    char** result = (char**)malloc(sizeof(char*) * cap);\n"
            "    int count = 0;\n"
            "    const char* p = s;\n"
            "    while (*p) {\n"
            "        const char* found = strstr(p, delim);\n"
            "        int seglen = found ? (int)(found - p) : (int)strlen(p);\n"
            "        if (count + 2 > cap) { cap *= 2; result = (char**)realloc(result, sizeof(char*) * cap); }\n"
            "        result[count] = (char*)malloc(seglen + 1);\n"
            "        memcpy(result[count], p, seglen);\n"
            "        result[count][seglen] = '\\0';\n"
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
        c_source=(
            "static inline char* __btrc_repeat(const char* s, int count) {\n"
            '    if (count < 0) { fprintf(stderr, "repeat count must be non-negative\\n"); exit(1); }\n'
            "    if (count == 0) { char* r = (char*)malloc(1); r[0] = '\\0'; return r; }\n"
            "    int slen = (int)strlen(s);\n"
            "    char* result = (char*)malloc((size_t)slen * count + 1);\n"
            "    for (int i = 0; i < count; i++) memcpy(result + i * slen, s, slen);\n"
            "    result[slen * count] = '\\0';\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_reverse": HelperDef(
        c_source=(
            "static inline char* __btrc_reverse(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    char* r = (char*)malloc(len + 1);\n"
            "    for (int i = 0; i < len; i++) r[i] = s[len - 1 - i];\n"
            "    r[len] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_isEmpty": HelperDef(
        c_source=(
            "static inline bool __btrc_isEmpty(const char* s) {\n"
            "    return s[0] == '\\0';\n"
            "}"
        ),
    ),
    "__btrc_removePrefix": HelperDef(
        c_source=(
            "static inline char* __btrc_removePrefix(const char* s, const char* prefix) {\n"
            "    int plen = (int)strlen(prefix);\n"
            "    if (strncmp(s, prefix, plen) == 0) {\n"
            "        int rlen = (int)strlen(s) - plen;\n"
            "        char* r = (char*)malloc(rlen + 1);\n"
            "        memcpy(r, s + plen, rlen + 1);\n"
            "        return r;\n"
            "    }\n"
            "    return strdup(s);\n"
            "}"
        ),
    ),
    "__btrc_removeSuffix": HelperDef(
        c_source=(
            "static inline char* __btrc_removeSuffix(const char* s, const char* suffix) {\n"
            "    int slen = (int)strlen(s);\n"
            "    int suflen = (int)strlen(suffix);\n"
            "    if (slen >= suflen && strcmp(s + slen - suflen, suffix) == 0) {\n"
            "        int rlen = slen - suflen;\n"
            "        char* r = (char*)malloc(rlen + 1);\n"
            "        memcpy(r, s, rlen);\n"
            "        r[rlen] = '\\0';\n"
            "        return r;\n"
            "    }\n"
            "    return strdup(s);\n"
            "}"
        ),
    ),
    "__btrc_startsWith": HelperDef(
        c_source=(
            "static inline bool __btrc_startsWith(const char* s, const char* prefix) {\n"
            "    return strncmp(s, prefix, strlen(prefix)) == 0;\n"
            "}"
        ),
    ),
    "__btrc_endsWith": HelperDef(
        c_source=(
            "static inline bool __btrc_endsWith(const char* s, const char* suffix) {\n"
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
            "    return strstr(s, sub) != NULL;\n"
            "}"
        ),
    ),
    "__btrc_capitalize": HelperDef(
        c_source=(
            "static inline char* __btrc_capitalize(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    char* r = (char*)malloc(len + 1);\n"
            "    for (int i = 0; i < len; i++) r[i] = tolower((unsigned char)s[i]);\n"
            "    if (len > 0) r[0] = toupper((unsigned char)r[0]);\n"
            "    r[len] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_title": HelperDef(
        c_source=(
            "static inline char* __btrc_title(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    char* r = (char*)malloc(len + 1);\n"
            "    int cap_next = 1;\n"
            "    for (int i = 0; i < len; i++) {\n"
            "        if (isspace((unsigned char)s[i])) { r[i] = s[i]; cap_next = 1; }\n"
            "        else if (cap_next) { r[i] = toupper((unsigned char)s[i]); cap_next = 0; }\n"
            "        else { r[i] = tolower((unsigned char)s[i]); }\n"
            "    }\n"
            "    r[len] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_swapCase": HelperDef(
        c_source=(
            "static inline char* __btrc_swapCase(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    char* r = (char*)malloc(len + 1);\n"
            "    for (int i = 0; i < len; i++) {\n"
            "        if (isupper((unsigned char)s[i])) r[i] = tolower((unsigned char)s[i]);\n"
            "        else if (islower((unsigned char)s[i])) r[i] = toupper((unsigned char)s[i]);\n"
            "        else r[i] = s[i];\n"
            "    }\n"
            "    r[len] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_padLeft": HelperDef(
        c_source=(
            "static inline char* __btrc_padLeft(const char* s, int width, char fill) {\n"
            "    int len = (int)strlen(s);\n"
            "    if (len >= width) { char* r = (char*)malloc(len + 1); memcpy(r, s, len); r[len] = '\\0'; return r; }\n"
            "    char* r = (char*)malloc(width + 1);\n"
            "    int pad = width - len;\n"
            "    memset(r, fill, pad);\n"
            "    memcpy(r + pad, s, len);\n"
            "    r[width] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_padRight": HelperDef(
        c_source=(
            "static inline char* __btrc_padRight(const char* s, int width, char fill) {\n"
            "    int len = (int)strlen(s);\n"
            "    if (len >= width) { char* r = (char*)malloc(len + 1); memcpy(r, s, len); r[len] = '\\0'; return r; }\n"
            "    char* r = (char*)malloc(width + 1);\n"
            "    memcpy(r, s, len);\n"
            "    memset(r + len, fill, width - len);\n"
            "    r[width] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_center": HelperDef(
        c_source=(
            "static inline char* __btrc_center(const char* s, int width, char fill) {\n"
            "    int len = (int)strlen(s);\n"
            "    if (len >= width) { char* r = (char*)malloc(len + 1); memcpy(r, s, len); r[len] = '\\0'; return r; }\n"
            "    char* r = (char*)malloc(width + 1);\n"
            "    int left = (width - len) / 2;\n"
            "    int right = width - len - left;\n"
            "    memset(r, fill, left);\n"
            "    memcpy(r + left, s, len);\n"
            "    memset(r + left + len, fill, right);\n"
            "    r[width] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_lstrip": HelperDef(
        c_source=(
            "static inline char* __btrc_lstrip(const char* s) {\n"
            "    while (*s && isspace((unsigned char)*s)) s++;\n"
            "    char* r = (char*)malloc(strlen(s) + 1);\n"
            "    { int __n = (int)strlen(s); memcpy(r, s, __n); r[__n] = '\\0'; }\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_rstrip": HelperDef(
        c_source=(
            "static inline char* __btrc_rstrip(const char* s) {\n"
            "    int len = (int)strlen(s);\n"
            "    while (len > 0 && isspace((unsigned char)s[len - 1])) len--;\n"
            "    char* r = (char*)malloc(len + 1);\n"
            "    memcpy(r, s, len);\n"
            "    r[len] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_count": HelperDef(
        c_source=(
            "static inline int __btrc_count(const char* s, const char* sub) {\n"
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
            "    int len = (int)strlen(s);\n"
            "    if (start < 0 || start >= len) return -1;\n"
            "    const char* found = strstr(s + start, sub);\n"
            "    if (!found) return -1;\n"
            "    return (int)(found - s);\n"
            "}"
        ),
    ),
    "__btrc_fromInt": HelperDef(
        c_source=(
            "static inline char* __btrc_fromInt(int n) {\n"
            "    char* r = (char*)malloc(21);\n"
            '    snprintf(r, 21, "%d", n);\n'
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_fromFloat": HelperDef(
        c_source=(
            "static inline char* __btrc_fromFloat(float f) {\n"
            "    char* r = (char*)malloc(32);\n"
            '    snprintf(r, 32, "%g", (double)f);\n'
            "    return r;\n"
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
    "__btrc_intToString": HelperDef(
        c_source=(
            "static inline char* __btrc_intToString(int n) {\n"
            "    char* buf = (char*)malloc(32);\n"
            '    snprintf(buf, 32, "%d", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_longToString": HelperDef(
        c_source=(
            "static inline char* __btrc_longToString(long n) {\n"
            "    char* buf = (char*)malloc(32);\n"
            '    snprintf(buf, 32, "%ld", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_floatToString": HelperDef(
        c_source=(
            "static inline char* __btrc_floatToString(float f) {\n"
            "    char* buf = (char*)malloc(64);\n"
            '    snprintf(buf, 64, "%g", (double)f);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_doubleToString": HelperDef(
        c_source=(
            "static inline char* __btrc_doubleToString(double d) {\n"
            "    char* buf = (char*)malloc(64);\n"
            '    snprintf(buf, 64, "%g", d);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_charToString": HelperDef(
        c_source=(
            "static inline char* __btrc_charToString(char c) {\n"
            "    char* buf = (char*)malloc(2);\n"
            "    buf[0] = c; buf[1] = '\\0';\n"
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_zfill": HelperDef(
        c_source=(
            "static inline char* __btrc_zfill(const char* s, int width) {\n"
            "    int len = (int)strlen(s);\n"
            "    if (len >= width) return strdup(s);\n"
            "    char* r = (char*)malloc(width + 1);\n"
            "    int pad = width - len;\n"
            "    int start = 0;\n"
            "    if (s[0] == '-' || s[0] == '+') { r[0] = s[0]; start = 1; }\n"
            "    for (int i = start; i < start + pad; i++) r[i] = '0';\n"
            "    memcpy(r + start + pad, s + start, len - start);\n"
            "    r[width] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_join": HelperDef(
        c_source=(
            "static inline char* __btrc_join(char** items, int count, const char* sep) {\n"
            "    if (count == 0) { char* r = (char*)malloc(1); r[0] = '\\0'; return r; }\n"
            "    int seplen = (int)strlen(sep);\n"
            "    int total = 0;\n"
            "    for (int i = 0; i < count; i++) total += (int)strlen(items[i]);\n"
            "    total += seplen * (count - 1);\n"
            "    char* r = (char*)malloc(total + 1);\n"
            "    int pos = 0;\n"
            "    for (int i = 0; i < count; i++) {\n"
            "        if (i > 0) { memcpy(r + pos, sep, seplen); pos += seplen; }\n"
            "        int len = (int)strlen(items[i]);\n"
            "        memcpy(r + pos, items[i], len);\n"
            "        pos += len;\n"
            "    }\n"
            "    r[pos] = '\\0';\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_strcat": HelperDef(
        c_source=(
            "static inline char* __btrc_strcat(const char* a, const char* b) {\n"
            "    int la = (int)strlen(a), lb = (int)strlen(b);\n"
            "    char* r = (char*)malloc(la + lb + 1);\n"
            "    memcpy(r, a, la);\n"
            "    memcpy(r + la, b, lb + 1);\n"
            "    return r;\n"
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
