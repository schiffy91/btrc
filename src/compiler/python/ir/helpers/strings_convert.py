"""String conversion helpers — toString, fromInt, fromFloat."""

from .core import HelperDef

STRING_CONVERT = {
    "__btrc_parseLong": HelperDef(
        c_source=(
            "static inline long __btrc_parseLong(const char* s) {\n"
            "    if (!s) return 0;\n"
            "    while (*s == ' ' || *s == '\\t' || *s == '\\n'\n"
            "            || *s == '\\r' || *s == '\\v' || *s == '\\f') ++s;\n"
            "    bool negative = false;\n"
            "    if (*s == '-' || *s == '+') { negative = *s == '-'; ++s; }\n"
            "    unsigned long limit = negative\n"
            "        ? (unsigned long)LONG_MAX + 1UL : (unsigned long)LONG_MAX;\n"
            "    unsigned long value = 0UL;\n"
            "    bool any = false;\n"
            "    while (*s >= '0' && *s <= '9') {\n"
            "        unsigned long digit = (unsigned long)(*s - '0');\n"
            "        any = true;\n"
            "        if (value > (limit - digit) / 10UL)\n"
            "            return negative ? LONG_MIN : LONG_MAX;\n"
            "        value = value * 10UL + digit;\n"
            "        ++s;\n"
            "    }\n"
            "    if (!any) return 0L;\n"
            "    if (!negative) return (long)value;\n"
            "    if (value == (unsigned long)LONG_MAX + 1UL) return LONG_MIN;\n"
            "    return -(long)value;\n"
            "}"
        ),
    ),
    "__btrc_parseInt": HelperDef(
        depends_on=["__btrc_parseLong"],
        c_source=(
            "static inline int __btrc_parseInt(const char* s) {\n"
            "    long value = __btrc_parseLong(s);\n"
            "    if (value > INT_MAX) return INT_MAX;\n"
            "    if (value < INT_MIN) return INT_MIN;\n"
            "    return (int)value;\n"
            "}"
        ),
    ),
    "__btrc_parseBool": HelperDef(
        c_source=(
            "static inline bool __btrc_parseBool(const char* s) {\n"
            "    return s && *s != '\\0' && strcmp(s, \"false\") != 0\n"
            '        && strcmp(s, "0") != 0;\n'
            "}"
        ),
    ),
    "__btrc_intToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_intToString(int n) {\n"
            "    char* buf = __btrc_string_alloc(31);\n"
            '    snprintf(buf, 32, "%d", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_longToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_longToString(long n) {\n"
            "    char* buf = __btrc_string_alloc(31);\n"
            '    snprintf(buf, 32, "%ld", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_longLongToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_longLongToString(long long n) {\n"
            "    char* buf = __btrc_string_alloc(31);\n"
            '    snprintf(buf, 32, "%lld", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_uintToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_uintToString(unsigned int n) {\n"
            "    char* buf = __btrc_string_alloc(31);\n"
            '    snprintf(buf, 32, "%u", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_ulongToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_ulongToString(unsigned long n) {\n"
            "    char* buf = __btrc_string_alloc(31);\n"
            '    snprintf(buf, 32, "%lu", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_ulongLongToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_ulongLongToString(unsigned long long n) {\n"
            "    char* buf = __btrc_string_alloc(31);\n"
            '    snprintf(buf, 32, "%llu", n);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_floatToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_floatToString(float f) {\n"
            "    char* buf = __btrc_string_alloc(63);\n"
            '    snprintf(buf, 64, "%g", (double)f);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_doubleToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_doubleToString(double d) {\n"
            "    char* buf = __btrc_string_alloc(63);\n"
            '    snprintf(buf, 64, "%g", d);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_longDoubleToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_longDoubleToString(long double d) {\n"
            "    char* buf = __btrc_string_alloc(63);\n"
            '    snprintf(buf, 64, "%Lg", d);\n'
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_charToString": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_charToString(char c) {\n"
            "    char* buf = __btrc_string_alloc(1);\n"
            "    buf[0] = c; buf[1] = '\\0';\n"
            "    return buf;\n"
            "}"
        ),
    ),
    "__btrc_fromInt": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_fromInt(int n) {\n"
            "    char* r = __btrc_string_alloc(20);\n"
            '    snprintf(r, 21, "%d", n);\n'
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_fromFloat": HelperDef(
        depends_on=["__btrc_string_alloc"],
        c_source=(
            "static inline char* __btrc_fromFloat(float f) {\n"
            "    char* r = __btrc_string_alloc(31);\n"
            '    snprintf(r, 32, "%g", (double)f);\n'
            "    return r;\n"
            "}"
        ),
    ),
}
