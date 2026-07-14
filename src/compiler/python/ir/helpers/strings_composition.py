"""String concatenation and multi-item joining helpers."""

from .core import HelperDef

_ALLOC = ["__btrc_string_length", "__btrc_string_alloc"]

STRING_COMPOSITION = {
    "__btrc_strcat": HelperDef(
        depends_on=[*_ALLOC, "__btrc_strdup"],
        c_source=(
            "static inline char* __btrc_strcat(const char* a, const char* b) {\n"
            "    if (!a && !b) return __btrc_string_alloc(0);\n"
            "    if (!a) return __btrc_strdup(b);\n"
            "    if (!b) return __btrc_strdup(a);\n"
            "    int left_len = __btrc_string_length(a);\n"
            "    int right_len = __btrc_string_length(b);\n"
            "    if (right_len > INT_MAX - left_len) {\n"
            '        fprintf(stderr, "btrc: string concatenation overflow\\n"); exit(1);\n'
            "    }\n"
            "    int total = left_len + right_len;\n"
            "    char* result = __btrc_string_alloc(total);\n"
            "    memcpy(result, a, (size_t)left_len);\n"
            "    memcpy(result + left_len, b, (size_t)right_len);\n"
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_join": HelperDef(
        depends_on=_ALLOC,
        c_source=(
            "static inline char* __btrc_join(char** items, int count, const char* sep) {\n"
            "    if (count <= 0 || !items) return __btrc_string_alloc(0);\n"
            '    if (!sep) sep = "";\n'
            "    int separator_len = __btrc_string_length(sep);\n"
            "    long long total = (long long)separator_len * (long long)(count - 1);\n"
            "    if (total > INT_MAX) {\n"
            '        fprintf(stderr, "btrc: string join overflow\\n"); exit(1);\n'
            "    }\n"
            "    for (int i = 0; i < count; i++) {\n"
            "        int item_len = __btrc_string_length(items[i]);\n"
            "        if (item_len > INT_MAX - (int)total) {\n"
            '            fprintf(stderr, "btrc: string join overflow\\n"); exit(1);\n'
            "        }\n"
            "        total += item_len;\n"
            "    }\n"
            "    char* result = __btrc_string_alloc((int)total);\n"
            "    int position = 0;\n"
            "    for (int i = 0; i < count; i++) {\n"
            "        if (i > 0) {\n"
            "            memcpy(result + position, sep, (size_t)separator_len);\n"
            "            position += separator_len;\n"
            "        }\n"
            '        const char* item = items[i] ? items[i] : "";\n'
            "        int item_len = __btrc_string_length(item);\n"
            "        memcpy(result + position, item, (size_t)item_len);\n"
            "        position += item_len;\n"
            "    }\n"
            "    return result;\n"
            "}"
        ),
    ),
}
