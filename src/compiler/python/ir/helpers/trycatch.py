"""Try/catch runtime helpers -- setjmp/longjmp-based try/catch runtime with cleanup."""

from .core import HelperDef

TRYCATCH = {
    "__btrc_trycatch_globals": HelperDef(
        c_source=(
            "/* btrc try/catch runtime (dynamic) */\n"
            "static __thread int __btrc_try_cap = 16;\n"
            "static __thread jmp_buf* __btrc_try_stack = NULL;\n"
            "static __thread int __btrc_try_top = -1;\n"
            'static __thread char __btrc_error_msg[1024] = "";'
        ),
    ),
    "__btrc_cleanup_types": HelperDef(
        c_source=(
            "/* Cleanup stack: tracks heap resources to free on exception */\n"
            "typedef void (*__btrc_cleanup_fn)(void*);\n"
            "typedef struct { void** ptr_ref; __btrc_cleanup_fn fn; int try_level; } __btrc_cleanup_entry;\n"
            "static __thread int __btrc_cleanup_cap = 64;\n"
            "static __thread __btrc_cleanup_entry* __btrc_cleanup_stack = NULL;\n"
            "static __thread int __btrc_cleanup_top = -1;"
        ),
        depends_on=["__btrc_trycatch_globals"],
    ),
    "__btrc_register_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_register_cleanup(void** ptr_ref, __btrc_cleanup_fn fn) {\n"
            "    if (!__btrc_cleanup_stack) {\n"
            "        __btrc_cleanup_stack = (__btrc_cleanup_entry*)malloc(sizeof(__btrc_cleanup_entry) * __btrc_cleanup_cap);\n"
            "    }\n"
            "    if (__btrc_cleanup_top + 1 >= __btrc_cleanup_cap) {\n"
            "        __btrc_cleanup_cap *= 2;\n"
            "        __btrc_cleanup_stack = (__btrc_cleanup_entry*)realloc(\n"
            "            __btrc_cleanup_stack, sizeof(__btrc_cleanup_entry) * __btrc_cleanup_cap);\n"
            '        if (!__btrc_cleanup_stack) { fprintf(stderr, "btrc: cleanup stack OOM\\n"); exit(1); }\n'
            "    }\n"
            "    __btrc_cleanup_top++;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].ptr_ref = ptr_ref;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].fn = fn;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].try_level = __btrc_try_top;\n"
            "}"
        ),
        depends_on=["__btrc_cleanup_types"],
    ),
    "__btrc_run_cleanups": HelperDef(
        c_source=(
            "static inline void __btrc_run_cleanups(int level) {\n"
            "    while (__btrc_cleanup_top >= 0 && __btrc_cleanup_stack[__btrc_cleanup_top].try_level >= level) {\n"
            "        __btrc_cleanup_entry e = __btrc_cleanup_stack[__btrc_cleanup_top--];\n"
            "        if (e.fn && e.ptr_ref && *e.ptr_ref) { e.fn(*e.ptr_ref); *e.ptr_ref = NULL; }\n"
            "    }\n"
            "}"
        ),
        depends_on=["__btrc_cleanup_types"],
    ),
    "__btrc_discard_cleanups": HelperDef(
        c_source=(
            "static inline void __btrc_discard_cleanups(int level) {\n"
            "    while (__btrc_cleanup_top >= 0 &&\n"
            "           __btrc_cleanup_stack[__btrc_cleanup_top].try_level >= level) {\n"
            "        __btrc_cleanup_top--;\n"
            "    }\n"
            "}"
        ),
        depends_on=["__btrc_cleanup_types"],
    ),
    "__btrc_throw": HelperDef(
        c_source=(
            "static inline void __btrc_throw(const char* msg) {\n"
            "    if (__btrc_try_top < 0) {\n"
            '        fprintf(stderr, "Unhandled exception: %s\\n", msg);\n'
            "        exit(1);\n"
            "    }\n"
            "    strncpy(__btrc_error_msg, msg, 1023);\n"
            "    __btrc_error_msg[1023] = '\\0';\n"
            "    __btrc_run_cleanups(__btrc_try_top);\n"
            "    longjmp(__btrc_try_stack[__btrc_try_top--], 1);\n"
            "}"
        ),
        depends_on=["__btrc_trycatch_globals", "__btrc_run_cleanups"],
    ),
}
