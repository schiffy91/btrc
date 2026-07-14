"""String padding, whitespace stripping, and zero-fill helpers."""

from .core import HelperDef
from .strings_common import NULL_RET_EMPTY

_ALLOC = ["__btrc_string_length", "__btrc_string_alloc"]

STRING_LAYOUT = {
    "__btrc_padLeft": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_padLeft(const char* s, int width, char fill) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    int result_len = len >= width ? len : width;\n"
            "    char* result = __btrc_string_alloc(result_len);\n"
            "    int pad = result_len - len;\n"
            "    memset(result, (unsigned char)fill, (size_t)pad);\n"
            "    memcpy(result + pad, s, (size_t)len);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_padRight": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_padRight(const char* s, int width, char fill) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    int result_len = len >= width ? len : width;\n"
            "    char* result = __btrc_string_alloc(result_len);\n"
            "    memcpy(result, s, (size_t)len);\n"
            "    memset(result + len, (unsigned char)fill, (size_t)(result_len - len));\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_center": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_center(const char* s, int width, char fill) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    int result_len = len >= width ? len : width;\n"
            "    char* result = __btrc_string_alloc(result_len);\n"
            "    int left = (result_len - len) / 2;\n"
            "    int right = result_len - len - left;\n"
            "    memset(result, (unsigned char)fill, (size_t)left);\n"
            "    memcpy(result + left, s, (size_t)len);\n"
            "    memset(result + left + len, (unsigned char)fill, (size_t)right);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_lstrip": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_space"],
        c_source=(
            "static inline char* __btrc_lstrip(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    int start = 0;\n"
            "    while (start < len && __btrc_ascii_space(s[start])) start++;\n"
            "    int result_len = len - start;\n"
            "    char* result = __btrc_string_alloc(result_len);\n"
            "    memcpy(result, s + start, (size_t)result_len);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_rstrip": HelperDef(
        depends_on=[*_ALLOC, "__btrc_ascii_space"],
        c_source=(
            "static inline char* __btrc_rstrip(const char* s) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    while (len > 0 && __btrc_ascii_space(s[len - 1])) len--;\n"
            "    char* result = __btrc_string_alloc(len);\n"
            "    memcpy(result, s, (size_t)len);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_zfill": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_zfill(const char* s, int width) {\n"
            + NULL_RET_EMPTY
            + "    int len = __btrc_string_length(s);\n"
            "    int result_len = len >= width ? len : width;\n"
            "    char* result = __btrc_string_alloc(result_len);\n"
            "    int start = (len > 0 && (s[0] == '-' || s[0] == '+')) ? 1 : 0;\n"
            "    int pad = result_len - len;\n"
            "    if (start) result[0] = s[0];\n"
            "    memset(result + start, '0', (size_t)pad);\n"
            "    memcpy(result + start + pad, s + start, (size_t)(len - start));\n"
            "    return result;\n"
            "}"
        ),
    ),
}
