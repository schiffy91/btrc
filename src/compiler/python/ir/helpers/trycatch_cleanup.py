"""Typed exception-cleanup registry helpers."""

from .core import HelperDef

TRYCATCH_CLEANUP = {
    "__btrc_cleanup_types": HelperDef(
        c_source=(
            "/* Cleanup slots are opaque; generated adapters access their exact type. */\n"
            "typedef __btrc_destroy_fn __btrc_cleanup_fn;\n"
            "typedef void* (*__btrc_cleanup_take_fn)(void*);\n"
            "typedef struct { void* slot; __btrc_cleanup_take_fn take; __btrc_cleanup_fn fn; "
            "__btrc_visit_fn visit; int try_level; int direct; } __btrc_cleanup_entry;\n"
            "static _Thread_local __btrc_cleanup_entry* __btrc_cleanup_stack = NULL;\n"
            "static _Thread_local int __btrc_cleanup_top = -1;"
        ),
        depends_on=["__btrc_try_level", "__btrc_arc_callback_types"],
    ),
    "__btrc_cleanup_capacity": HelperDef(
        c_source="static _Thread_local int __btrc_cleanup_cap = 64;",
    ),
    "__btrc_register_cleanup_kind": HelperDef(
        c_source=(
            "static inline void __btrc_register_cleanup_kind(\n"
            "        void* slot, __btrc_cleanup_take_fn take,\n"
            "        __btrc_cleanup_fn fn, __btrc_visit_fn visit, int direct) {\n"
            "    if (!slot || !take || !fn) return;\n"
            "    for (int i = __btrc_cleanup_top; i >= 0; i--) {\n"
            "        __btrc_cleanup_entry* existing = &__btrc_cleanup_stack[i];\n"
            "        if (existing->try_level == __btrc_try_top && existing->slot == slot) {\n"
            "            existing->take = take;\n"
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
            "    __btrc_cleanup_stack[__btrc_cleanup_top] = (__btrc_cleanup_entry){\n"
            "        slot, take, fn, visit, __btrc_try_top, direct};\n"
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
            "        void* slot, __btrc_cleanup_take_fn take,\n"
            "        __btrc_cleanup_fn fn, __btrc_visit_fn visit) {\n"
            "    __btrc_register_cleanup_kind(slot, take, fn, visit, 0);\n"
            "}"
        ),
        depends_on=["__btrc_register_cleanup_kind"],
    ),
    "__btrc_register_direct_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_register_direct_cleanup(\n"
            "        void* slot, __btrc_cleanup_take_fn take, __btrc_cleanup_fn fn) {\n"
            "    __btrc_register_cleanup_kind(slot, take, fn, NULL, 1);\n"
            "}"
        ),
        depends_on=["__btrc_register_cleanup_kind"],
    ),
    "__btrc_run_cleanups": HelperDef(
        c_source=(
            "static inline void __btrc_run_cleanups(int level) {\n"
            "    int base = __btrc_cleanup_top;\n"
            "    while (base >= 0 && __btrc_cleanup_stack[base].try_level >= level) base--;\n"
            "    base++;\n"
            "    if (base > __btrc_cleanup_top) return;\n"
            "    int count = __btrc_cleanup_top - base + 1;\n"
            '    if ((size_t)count > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup batch size overflow\\n"); exit(1); }\n'
            "    __btrc_cleanup_entry* entries = (__btrc_cleanup_entry*)__btrc_safe_realloc(\n"
            "        NULL, sizeof(__btrc_cleanup_entry) * (size_t)count);\n"
            "    memcpy(entries, &__btrc_cleanup_stack[base],\n"
            "        sizeof(__btrc_cleanup_entry) * (size_t)count);\n"
            "    __btrc_cleanup_top = base - 1;\n"
            "    char primary_error[sizeof __btrc_error_msg];\n"
            "    memcpy(primary_error, __btrc_error_msg, sizeof primary_error);\n"
            "    __btrc_destroyed_tracking_begin();\n"
            "    for (int i = count - 1; i >= 0; i--) {\n"
            "        __btrc_cleanup_entry entry = entries[i];\n"
            "        if (!entry.fn || !entry.slot || !entry.take) continue;\n"
            "        void* object = entry.take(entry.slot);\n"
            "        if (!object) continue;\n"
            "        if (!entry.direct && __btrc_is_destroyed(object)) continue;\n"
            "        __btrc_push_try();\n"
            "        int guard_level = __btrc_try_top;\n"
            "        if (setjmp(__btrc_try_stack[guard_level]->env) == 0) {\n"
            "            if (entry.direct) {\n"
            "                entry.fn(object);\n"
            "            } else {\n"
            "                __btrc_arc_type type = {entry.visit, entry.fn};\n"
            "                if (entry.visit) __btrc_arc_release(object, &type);\n"
            "                else __btrc_arc_release_acyclic(object, &type);\n"
            "            }\n"
            "            __btrc_try_top--;\n"
            "        }\n"
            "        memcpy(__btrc_error_msg, primary_error, sizeof primary_error);\n"
            "    }\n"
            "    __btrc_push_try();\n"
            "    int flush_guard_level = __btrc_try_top;\n"
            "    if (setjmp(__btrc_try_stack[flush_guard_level]->env) == 0) {\n"
            "        __btrc_flush_cycles();\n"
            "        __btrc_try_top--;\n"
            "    }\n"
            "    memcpy(__btrc_error_msg, primary_error, sizeof primary_error);\n"
            "    __btrc_destroyed_tracking_end();\n"
            "    free(entries);\n"
            "}"
        ),
        depends_on=[
            "__btrc_cleanup_types",
            "__btrc_push_try",
            "__btrc_safe_realloc",
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
        c_source="static inline int __btrc_cleanup_mark(void) { return __btrc_cleanup_top; }",
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
}

__all__ = ["TRYCATCH_CLEANUP"]
