"""Alloc runtime helpers -- safe wrappers for realloc/calloc (always emitted)."""

from .core import HelperDef

ALLOC = {
    "__btrc_strdup": HelperDef(
        c_source=(
            "static inline char* __btrc_strdup(const char* s) {\n"
            "    if (!s) return NULL;\n"
            "    size_t len = strlen(s) + 1;\n"
            "    char* copy = (char*)malloc(len);\n"
            '    if (!copy) { fprintf(stderr, "btrc: out of memory (strdup %zu bytes)\\n", len); exit(1); }\n'
            "    memcpy(copy, s, len);\n"
            "    return copy;\n"
            "}"
        ),
    ),
    "__btrc_safe_realloc": HelperDef(
        c_source=(
            "static inline void* __btrc_safe_realloc(void* ptr, size_t size) {\n"
            "    void* result = realloc(ptr, size);\n"
            '    if (!result && size > 0) { fprintf(stderr, "btrc: out of memory (realloc %zu bytes)\\n", size); exit(1); }\n'
            "    return result;\n"
            "}"
        ),
    ),
    "__btrc_safe_calloc": HelperDef(
        c_source=(
            "static inline void* __btrc_safe_calloc(size_t count, size_t size) {\n"
            "    void* result = calloc(count, size);\n"
            '    if (!result && count > 0) { fprintf(stderr, "btrc: out of memory (calloc %zu bytes)\\n", count * size); exit(1); }\n'
            "    return result;\n"
            "}"
        ),
    ),
}
