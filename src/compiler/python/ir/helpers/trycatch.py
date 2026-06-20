"""Try/catch runtime helpers -- setjmp/longjmp-based try/catch runtime with cleanup."""

from .core import HelperDef

TRYCATCH = {
    "__btrc_trycatch_globals": HelperDef(
        c_source=(
            "/* btrc try/catch runtime (dynamic) */\n"
            "static __thread int __btrc_try_cap = 16;\n"
            "static __thread jmp_buf* __btrc_try_stack = NULL;\n"
            # __btrc_try_top is incremented before setjmp and decremented by the
            # throw / normal-exit paths, so its value crosses the setjmp/longjmp
            # boundary. Per C11 7.13.2.1 an object whose value changes between
            # setjmp and longjmp has an indeterminate value after the longjmp
            # unless it is volatile. Marking it volatile also serves as the
            # optimization barrier that stops gcc -O2 from CSE-merging the work
            # in the setjmp(...)==0 and catch branches across the branch (which
            # otherwise drops a returned object's field init -> wrong value).
            "static __thread volatile int __btrc_try_top = -1;\n"
            'static __thread char __btrc_error_msg[1024] = "";'
        ),
    ),
    "__btrc_cleanup_types": HelperDef(
        c_source=(
            "/* Cleanup stack: tracks heap resources to free on exception */\n"
            "typedef void (*__btrc_cleanup_fn)(void*);\n"
            "typedef struct { void** ptr_ref; __btrc_cleanup_fn fn; void* visit; int try_level; } __btrc_cleanup_entry;\n"
            "static __thread int __btrc_cleanup_cap = 64;\n"
            "static __thread __btrc_cleanup_entry* __btrc_cleanup_stack = NULL;\n"
            "static __thread int __btrc_cleanup_top = -1;"
        ),
        depends_on=["__btrc_trycatch_globals"],
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
            "static void* volatile __btrc_launder_slot;\n"
            "static inline void* __btrc_launder(void* p) {\n"
            "    __btrc_launder_slot = p;\n"
            "    return __btrc_launder_slot;\n"
            "}"
        ),
    ),
    "__btrc_register_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_register_cleanup(void** ptr_ref, __btrc_cleanup_fn fn, void* visit) {\n"
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
            "    __btrc_cleanup_stack[__btrc_cleanup_top].visit = visit;\n"
            "    __btrc_cleanup_stack[__btrc_cleanup_top].try_level = __btrc_try_top;\n"
            "}"
        ),
        depends_on=["__btrc_cleanup_types"],
    ),
    "__btrc_run_cleanups": HelperDef(
        c_source=(
            "/* Exception cleanup. Non-cyclable managed locals keep the original\n"
            " * unconditional-destroy semantics. Cyclable ones (those with a\n"
            " * registered visitor) go through the same phased release +\n"
            " * trial-deletion cycle collection as a normal scope exit, so\n"
            " * unwinding a scope that holds a reference cycle reclaims it without\n"
            " * a use-after-free: a plain per-node destroy would cascade-free one\n"
            " * node then read freed memory through the other node's back-edge.\n"
            " * __btrc_tracking + the destroyed log guard every cross-entry read. */\n"
            "static inline void __btrc_run_cleanups(int level) {\n"
            "    int base = __btrc_cleanup_top;\n"
            "    while (base >= 0 && __btrc_cleanup_stack[base].try_level >= level) { base--; }\n"
            "    base++;\n"
            "    if (base > __btrc_cleanup_top) { return; }\n"
            "    __btrc_tracking = 1;\n"
            "    __btrc_destroyed_count = 0;\n"
            "    /* Non-cyclable entries: unconditional destroy (original behavior),\n"
            "     * but skip any object already cascade-freed by an earlier destroy. */\n"
            "    for (int i = __btrc_cleanup_top; i >= base; i--) {\n"
            "        __btrc_cleanup_entry* e = &__btrc_cleanup_stack[i];\n"
            "        if (e->visit) { continue; }\n"
            "        if (e->fn && e->ptr_ref && *e->ptr_ref && !__btrc_is_destroyed(*e->ptr_ref)) {\n"
            "            e->fn(*e->ptr_ref);\n"
            "            *e->ptr_ref = NULL;\n"
            "        }\n"
            "    }\n"
            "    /* Cyclable entries: phased release + cycle collection.\n"
            "     * Phase 1 -- drop each managed local's own reference (rc--). */\n"
            "    for (int i = __btrc_cleanup_top; i >= base; i--) {\n"
            "        __btrc_cleanup_entry* e = &__btrc_cleanup_stack[i];\n"
            "        if (e->visit && e->ptr_ref && *e->ptr_ref) { (*(int*)*e->ptr_ref)--; }\n"
            "    }\n"
            "    /* Phase 2 -- destroy objects whose rc hit zero (destroyed-log guarded). */\n"
            "    for (int i = __btrc_cleanup_top; i >= base; i--) {\n"
            "        __btrc_cleanup_entry* e = &__btrc_cleanup_stack[i];\n"
            "        if (e->visit && e->fn && e->ptr_ref && *e->ptr_ref\n"
            "                && !__btrc_is_destroyed(*e->ptr_ref)\n"
            "                && *(int*)*e->ptr_ref <= 0) {\n"
            "            e->fn(*e->ptr_ref);\n"
            "            *e->ptr_ref = NULL;\n"
            "        }\n"
            "    }\n"
            "    /* Phase 3 -- still-referenced survivors are cycle suspects. */\n"
            "    for (int i = __btrc_cleanup_top; i >= base; i--) {\n"
            "        __btrc_cleanup_entry* e = &__btrc_cleanup_stack[i];\n"
            "        if (e->visit && e->fn && e->ptr_ref && *e->ptr_ref\n"
            "                && !__btrc_is_destroyed(*e->ptr_ref)\n"
            "                && *(int*)*e->ptr_ref > 0) {\n"
            "            __btrc_suspect(*e->ptr_ref, (__btrc_visit_fn)e->visit,\n"
            "                           (__btrc_destroy_fn)e->fn);\n"
            "        }\n"
            "    }\n"
            "    /* Phase 4 -- trial-deletion cycle collection over the suspects. */\n"
            "    if (__btrc_suspect_count > 0) { __btrc_collect_cycles(); }\n"
            "    __btrc_tracking = 0;\n"
            "    __btrc_cleanup_top = base - 1;\n"
            "}"
        ),
        # depends_on is read two ways: gen/helpers.collect_helpers treats entries
        # as helper NAMES (to pull the bodies into the module), while
        # optimizer._eliminate_dead_helpers treats them as CATEGORY names (to keep
        # them alive through DCE). The cycle-safe unwinder calls into the cycles
        # machinery by symbol (__btrc_suspect, __btrc_is_destroyed, ...) rather
        # than by helper name, so the optimizer's text-closure can't see those
        # edges -- hence both the helper names (for collect_helpers) and the
        # "cycles" category (for the optimizer) are listed.
        depends_on=[
            "__btrc_cleanup_types",
            "__btrc_destroyed_tracking",
            "__btrc_suspect_buf",
            "__btrc_collect_cycles",
            "cycles",
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
