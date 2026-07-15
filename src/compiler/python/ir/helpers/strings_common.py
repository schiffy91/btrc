"""Shared checked primitives used by string runtime helpers."""

from .core import HelperDef

STRING_COMMON = {
    "__btrc_string_or_empty": HelperDef(
        c_source=('static inline const char* __btrc_string_or_empty(const char* s) {\n    return s ? s : "";\n}'),
    ),
    "__btrc_string_length": HelperDef(
        c_source=(
            "static inline int __btrc_string_length(const char* s) {\n"
            "    if (!s) return 0;\n"
            "    size_t length = strlen(s);\n"
            "    if (length > (size_t)INT_MAX) {\n"
            '        fprintf(stderr, "btrc: string length overflow\\n"); exit(1);\n'
            "    }\n"
            "    return (int)length;\n"
            "}"
        ),
    ),
    "__btrc_string_alloc": HelperDef(
        depends_on=["__btrc_safe_realloc", "__btrc_string_adopt"],
        c_source=(
            "static inline char* __btrc_string_alloc(int length) {\n"
            "    if (length < 0) {\n"
            '        fprintf(stderr, "btrc: negative string allocation\\n"); exit(1);\n'
            "    }\n"
            "    char* result = (char*)__btrc_safe_realloc(\n"
            "        NULL, (size_t)length + 1);\n"
            "    result[length] = '\\0';\n"
            "    return __btrc_string_adopt(result);\n"
            "}"
        ),
    ),
    "__btrc_ascii_upper": HelperDef(
        c_source=(
            "static inline char __btrc_ascii_upper(char value) {\n"
            "    unsigned char byte = (unsigned char)value;\n"
            "    return (byte >= 'a' && byte <= 'z') ? (char)(byte - 'a' + 'A') : value;\n"
            "}"
        ),
    ),
    "__btrc_ascii_lower": HelperDef(
        c_source=(
            "static inline char __btrc_ascii_lower(char value) {\n"
            "    unsigned char byte = (unsigned char)value;\n"
            "    return (byte >= 'A' && byte <= 'Z') ? (char)(byte - 'A' + 'a') : value;\n"
            "}"
        ),
    ),
    "__btrc_ascii_space": HelperDef(
        c_source=(
            "static inline bool __btrc_ascii_space(char value) {\n"
            "    unsigned char byte = (unsigned char)value;\n"
            "    return byte == ' ' || (byte >= '\\t' && byte <= '\\r');\n"
            "}"
        ),
    ),
}

NULL_RET_EMPTY = "    if (!s) return __btrc_string_alloc(0);\n"
