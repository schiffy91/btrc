"""String pool runtime helpers -- temp string pool for auto-cleanup."""

from .core import HelperDef

STRING_POOL = {
    "__btrc_str_pool_globals": HelperDef(
        c_source=(
            "/* btrc string temp pool (dynamic) */\n"
            "static int __btrc_str_pool_cap = 256;\n"
            "static char** __btrc_str_pool = NULL;\n"
            "static int __btrc_str_pool_top = 0;"
        ),
    ),
    "__btrc_str_track": HelperDef(
        c_source=(
            "static inline char* __btrc_str_track(char* s) {\n"
            "    if (!__btrc_str_pool) {\n"
            "        __btrc_str_pool = (char**)malloc(sizeof(char*) * __btrc_str_pool_cap);\n"
            "    }\n"
            "    if (__btrc_str_pool_top >= __btrc_str_pool_cap) {\n"
            "        __btrc_str_pool_cap *= 2;\n"
            "        __btrc_str_pool = (char**)realloc(__btrc_str_pool, sizeof(char*) * __btrc_str_pool_cap);\n"
            '        if (!__btrc_str_pool) { fprintf(stderr, "btrc: string pool OOM\\n"); exit(1); }\n'
            "    }\n"
            "    __btrc_str_pool[__btrc_str_pool_top++] = s;\n"
            "    return s;\n"
            "}"
        ),
        depends_on=["__btrc_str_pool_globals"],
    ),
    "__btrc_str_flush": HelperDef(
        c_source=(
            "static inline void __btrc_str_flush(void) {\n"
            "    for (int i = 0; i < __btrc_str_pool_top; i++) {\n"
            "        free(__btrc_str_pool[i]);\n"
            "        __btrc_str_pool[i] = NULL;\n"
            "    }\n"
            "    __btrc_str_pool_top = 0;\n"
            "}"
        ),
        depends_on=["__btrc_str_pool_globals"],
    ),
}
