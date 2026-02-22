"""String conversion helpers — toString, fromInt, fromFloat."""

from .core import HelperDef

STRING_CONVERT = {
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
}
