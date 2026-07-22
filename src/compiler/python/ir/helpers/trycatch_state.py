"""Try-frame state and branch-stability helpers."""

from .core import HelperDef

TRYCATCH_STATE = {
    "__btrc_try_level": HelperDef(
        c_source="static _Thread_local volatile int __btrc_try_top = -1;",
    ),
    "__btrc_trycatch_globals": HelperDef(
        c_source=(
            "/* btrc try/catch runtime (dynamic) */\n"
            "typedef struct { jmp_buf env; } __btrc_try_frame;\n"
            "static _Thread_local __btrc_try_frame** __btrc_try_stack = NULL;\n"
            'static _Thread_local char __btrc_error_msg[1024] = "";'
        ),
        required_headers=["setjmp.h"],
        depends_on=["__btrc_try_level"],
    ),
    "__btrc_copy_error_message": HelperDef(
        c_source=(
            "static inline void __btrc_copy_error_message(\n"
            "        char* destination, size_t capacity, const char* source) {\n"
            "    if (!destination || capacity == 0) return;\n"
            "    if (!source) {\n"
            "        destination[0] = '\\0';\n"
            "        return;\n"
            "    }\n"
            "    size_t length = 0;\n"
            "    while (length < capacity - 1 && source[length] != '\\0') length++;\n"
            "    memmove(destination, source, length);\n"
            "    destination[length] = '\\0';\n"
            "}"
        ),
        required_headers=["string.h"],
    ),
    "__btrc_try_capacity": HelperDef(
        c_source="static _Thread_local int __btrc_try_cap = 16;",
    ),
    "__btrc_launder_state": HelperDef(
        c_source="static _Thread_local void* volatile __btrc_launder_slot;",
    ),
    "__btrc_launder": HelperDef(
        c_source=(
            "/* Opaque pointer launder used when returning a freshly-built object\n"
            " * out of a try/catch. gcc -O2 (e.g. nix's fortify hardening) runs\n"
            " * points-to / store-merging across the setjmp(...)==0 vs catch\n"
            " * branches and, for an object that does not otherwise escape, folds\n"
            " * the two branches' field inits together -- dropping the catch\n"
            " * object's initialization (its fields read back as the other\n"
            " * branch's values). Routing the pointer through a volatile slot\n"
            " * forces the object to escape, which defeats that miscompilation.\n"
            " * Pure C11; the volatile access is the optimization barrier. */\n"
            "static inline void* __btrc_launder(void* p) {\n"
            "    __btrc_launder_slot = p;\n"
            "    return __btrc_launder_slot;\n"
            "}"
        ),
        depends_on=["__btrc_launder_state"],
    ),
    "__btrc_push_try": HelperDef(
        c_source=(
            "static inline void __btrc_push_try(void) {\n"
            "    if (__btrc_try_cap < 1) __btrc_try_cap = 16;\n"
            '    if (__btrc_try_top == INT_MAX) { fprintf(stderr, "btrc: try stack overflow\\n"); exit(1); }\n'
            "    if (!__btrc_try_stack) {\n"
            '        if ((size_t)__btrc_try_cap > SIZE_MAX / sizeof(*__btrc_try_stack)) { fprintf(stderr, "btrc: try stack size overflow\\n"); exit(1); }\n'
            "        __btrc_try_stack = (__btrc_try_frame**)__btrc_safe_realloc(\n"
            "            NULL, sizeof(*__btrc_try_stack) * (size_t)__btrc_try_cap);\n"
            "        for (int i = 0; i < __btrc_try_cap; i++) __btrc_try_stack[i] = NULL;\n"
            "    }\n"
            "    if (__btrc_try_top + 1 >= __btrc_try_cap) {\n"
            '        if (__btrc_try_cap > INT_MAX / 2) { fprintf(stderr, "btrc: try stack capacity overflow\\n"); exit(1); }\n'
            "        int old_cap = __btrc_try_cap;\n"
            "        int new_cap = __btrc_try_cap * 2;\n"
            '        if ((size_t)new_cap > SIZE_MAX / sizeof(*__btrc_try_stack)) { fprintf(stderr, "btrc: try stack size overflow\\n"); exit(1); }\n'
            "        __btrc_try_stack = (__btrc_try_frame**)__btrc_safe_realloc(\n"
            "            __btrc_try_stack, sizeof(*__btrc_try_stack) * (size_t)new_cap);\n"
            "        for (int i = old_cap; i < new_cap; i++) __btrc_try_stack[i] = NULL;\n"
            "        __btrc_try_cap = new_cap;\n"
            "    }\n"
            "    __btrc_try_top++;\n"
            "    if (!__btrc_try_stack[__btrc_try_top]) {\n"
            "        __btrc_try_stack[__btrc_try_top] = (__btrc_try_frame*)\n"
            "            __btrc_safe_realloc(NULL, sizeof(__btrc_try_frame));\n"
            "    }\n"
            "}"
        ),
        depends_on=[
            "__btrc_trycatch_globals",
            "__btrc_try_capacity",
            "__btrc_safe_realloc",
        ],
    ),
}

__all__ = ["TRYCATCH_STATE"]
