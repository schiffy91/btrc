"""Try/catch runtime helpers -- setjmp/longjmp-based try/catch runtime with cleanup."""

from .core import HelperDef

TRYCATCH = {
    "__btrc_try_level": HelperDef(
        c_source=(
            # The level is shared by the cleanup stack and the setjmp stack.
            # Keep it separate so cleanup-only constructor guards do not pull
            # unused frame-capacity, frame-pointer, and error-buffer globals.
            # It changes across setjmp/longjmp and therefore must be volatile.
            "static _Thread_local volatile int __btrc_try_top = -1;"
        ),
    ),
    "__btrc_trycatch_globals": HelperDef(
        c_source=(
            "/* btrc try/catch runtime (dynamic) */\n"
            "static _Thread_local int __btrc_try_cap = 16;\n"
            "typedef struct { jmp_buf env; } __btrc_try_frame;\n"
            "static _Thread_local __btrc_try_frame** __btrc_try_stack = NULL;\n"
            'static _Thread_local char __btrc_error_msg[1024] = "";'
        ),
        required_headers=["setjmp.h"],
        depends_on=["__btrc_try_level"],
    ),
    "__btrc_cleanup_types": HelperDef(
        c_source=(
            "/* Cleanup stack: tracks heap resources to free on exception */\n"
            "typedef __btrc_destroy_fn __btrc_cleanup_fn;\n"
            "typedef struct { void** ptr_ref; __btrc_cleanup_fn fn; __btrc_visit_fn visit; int try_level; int direct; } __btrc_cleanup_entry;\n"
            "static _Thread_local __btrc_cleanup_entry* __btrc_cleanup_stack = NULL;\n"
            "static _Thread_local int __btrc_cleanup_top = -1;"
        ),
        depends_on=["__btrc_try_level", "__btrc_arc_callback_types"],
    ),
    "__btrc_cleanup_capacity": HelperDef(
        c_source="static _Thread_local int __btrc_cleanup_cap = 64;",
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
        depends_on=["__btrc_trycatch_globals", "__btrc_safe_realloc"],
    ),
    "__btrc_register_cleanup_kind": HelperDef(
        c_source=(
            "static inline void __btrc_register_cleanup_kind(void** ptr_ref, __btrc_cleanup_fn fn, __btrc_visit_fn visit, int direct) {\n"
            "    if (!ptr_ref || !fn) return;\n"
            "    for (int i = __btrc_cleanup_top; i >= 0; i--) {\n"
            "        __btrc_cleanup_entry* existing = &__btrc_cleanup_stack[i];\n"
            "        if (existing->try_level == __btrc_try_top && existing->ptr_ref == ptr_ref) {\n"
            "            existing->fn = fn;\n"
            "            existing->visit = visit;\n"
            "            existing->direct = direct;\n"
            "            return;\n"
            "        }\n"
            "    }\n"
            "    if (__btrc_cleanup_cap < 1) __btrc_cleanup_cap = 64;\n"
            "    if (!__btrc_cleanup_stack) {\n"
            '        if ((size_t)__btrc_cleanup_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflow\\n"); exit(1); }\n'
            "        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(\n"
            "            NULL, sizeof(__btrc_cleanup_entry) * (size_t)__btrc_cleanup_cap);\n"
            "    }\n"
            '    if (__btrc_cleanup_top == INT_MAX) { fprintf(stderr, "btrc: cleanup stack overflow\\n"); exit(1); }\n'
            "    if (__btrc_cleanup_top + 1 >= __btrc_cleanup_cap) {\n"
            '        if (__btrc_cleanup_cap > INT_MAX / 2) { fprintf(stderr, "btrc: cleanup stack capacity overflow\\n"); exit(1); }\n'
            "        int new_cap = __btrc_cleanup_cap * 2;\n"
            '        if ((size_t)new_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflow\\n"); exit(1); }\n'
            "        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(\n"
            "            __btrc_cleanup_stack, sizeof(__btrc_cleanup_entry) * (size_t)new_cap);\n"
            "        __btrc_cleanup_cap = new_cap;\n"
            "    }\n"
            "    __btrc_cleanup_top++;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].ptr_ref = ptr_ref;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].fn = fn;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].visit = visit;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].try_level = __btrc_try_top;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].direct = direct;\n"
            "}"
        ),
        depends_on=[
            "__btrc_cleanup_types",
            "__btrc_cleanup_capacity",
            "__btrc_safe_realloc",
        ],
    ),
    "__btrc_register_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_register_cleanup(\n"
            "        void** ptr_ref, __btrc_cleanup_fn fn,\n"
            "        __btrc_visit_fn visit) {\n"
            "    __btrc_register_cleanup_kind(ptr_ref, fn, visit, 0);\n"
            "}"
        ),
        depends_on=["__btrc_register_cleanup_kind"],
    ),
    "__btrc_register_direct_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_register_direct_cleanup(\n"
            "        void** ptr_ref, __btrc_cleanup_fn fn) {\n"
            "    __btrc_register_cleanup_kind(ptr_ref, fn, NULL, 1);\n"
            "}"
        ),
        depends_on=["__btrc_register_cleanup_kind"],
    ),
    "__btrc_run_cleanups": HelperDef(
        c_source=(
            "/* Exception cleanup uses the same typed release atoms as normal\n"
            " * scope exit. The destroyed log guards later entries from cascade\n"
            " * destruction; owned slots are cleared before one collector flush. */\n"
            "static inline void __btrc_run_cleanups(int level) {\n"
            "    int base = __btrc_cleanup_top;\n"
            "    while (base >= 0 && __btrc_cleanup_stack[base].try_level >= level) { base--; }\n"
            "    base++;\n"
            "    if (base > __btrc_cleanup_top) { return; }\n"
            "    __btrc_destroyed_tracking_begin();\n"
            "    for (int i = __btrc_cleanup_top; i >= base; i--) {\n"
            "        __btrc_cleanup_entry* e = &__btrc_cleanup_stack[i];\n"
            "        if (!e->fn || !e->ptr_ref || !*e->ptr_ref) { continue; }\n"
            "        void* object = *e->ptr_ref;\n"
            "        *e->ptr_ref = NULL;\n"
            "        if (e->direct) { e->fn(object); continue; }\n"
            "        if (__btrc_is_destroyed(object)) { continue; }\n"
            "        __btrc_arc_type type = {e->visit, e->fn};\n"
            "        if (e->visit) {\n"
            "            __btrc_arc_release(object, &type);\n"
            "        } else {\n"
            "            __btrc_arc_release_acyclic(object, &type);\n"
            "        }\n"
            "    }\n"
            "    __btrc_flush_cycles();\n"
            "    __btrc_destroyed_tracking_end();\n"
            "    __btrc_cleanup_top = base - 1;\n"
            "}"
        ),
        depends_on=[
            "__btrc_cleanup_types",
            "__btrc_destroyed_tracking_scope",
            "__btrc_is_destroyed",
            "__btrc_arc_release",
            "__btrc_arc_release_acyclic",
            "__btrc_flush_cycles",
        ],
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
    "__btrc_cleanup_mark": HelperDef(
        c_source=("static inline int __btrc_cleanup_mark(void) {\n    return __btrc_cleanup_top;\n}"),
        depends_on=["__btrc_cleanup_types"],
    ),
    "__btrc_discard_cleanups_to": HelperDef(
        c_source=(
            "static inline void __btrc_discard_cleanups_to(int mark) {\n"
            "    if (mark < -1 || mark > __btrc_cleanup_top) {\n"
            '        fprintf(stderr, "btrc: invalid cleanup scope marker\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    __btrc_cleanup_top = mark;\n"
            "}"
        ),
        depends_on=["__btrc_cleanup_types"],
    ),
    "__btrc_throw": HelperDef(
        c_source=(
            "static _Noreturn void __btrc_throw(const char* msg) {\n"
            '    const char* text = msg ? msg : "Unknown exception";\n'
            "    if (__btrc_try_top < 0) {\n"
            '        fprintf(stderr, "Unhandled exception: %s\\n", text);\n'
            "        exit(1);\n"
            "    }\n"
            "    strncpy(__btrc_error_msg, text, 1023);\n"
            "    __btrc_error_msg[1023] = '\\0';\n"
            "    __btrc_run_cleanups(__btrc_try_top);\n"
            "    int level = __btrc_try_top;\n"
            "    __btrc_try_top--;\n"
            "    longjmp(__btrc_try_stack[level]->env, 1);\n"
            "}"
        ),
        depends_on=["__btrc_trycatch_globals", "__btrc_run_cleanups"],
    ),
    "__btrc_try_state_cleanup": HelperDef(
        c_source=(
            "static void __btrc_try_state_cleanup(void) {\n"
            "    for (int i = 0; i < __btrc_try_cap; i++) {\n"
            "        free(__btrc_try_stack ? __btrc_try_stack[i] : NULL);\n"
            "    }\n"
            "    free(__btrc_try_stack);\n"
            "    free(__btrc_cleanup_stack);\n"
            "    __btrc_try_stack = NULL;\n"
            "    __btrc_cleanup_stack = NULL;\n"
            "    __btrc_try_cap = 16;\n"
            "    __btrc_cleanup_cap = 64;\n"
            "    __btrc_try_top = -1;\n"
            "    __btrc_cleanup_top = -1;\n"
            "    __btrc_error_msg[0] = '\\0';\n"
            "    __btrc_launder_slot = NULL;\n"
            "}"
        ),
        depends_on=[
            "__btrc_trycatch_globals",
            "__btrc_cleanup_types",
            "__btrc_cleanup_capacity",
            "__btrc_launder_state",
        ],
    ),
}
