/* btrc-runtime-helper:begin __btrc_try_level */
static _Thread_local volatile int __btrc_try_top = -1;
/* btrc-runtime-helper:end __btrc_try_level */
/* btrc-runtime-helper:begin __btrc_trycatch_globals */
/* btrc try/catch runtime (dynamic) */
/* Darwin and the BSDs make setjmp save the caller's signal mask and alternate
 * stack, which costs two syscalls on entry to every try block. btrc never
 * throws out of a signal handler, so that mask is not state a catch has to
 * restore; _setjmp/_longjmp are the POSIX spellings that leave it alone. A
 * freestanding shim owns its own spelling, and any other target keeps the C11
 * pair. Both spellings compile under -std=c11 -pedantic-errors on macOS/clang
 * and glibc/gcc. */
#if !defined(BTRC_TRY_SETJMP)
#if !defined(BTRC_RT_SETJMP_HEADER) \
        && (defined(__APPLE__) || defined(__unix__) || defined(__linux__))
#define BTRC_TRY_SETJMP(env) _setjmp(env)
#define BTRC_TRY_LONGJMP(env, value) _longjmp(env, value)
#else
#define BTRC_TRY_SETJMP(env) setjmp(env)
#define BTRC_TRY_LONGJMP(env, value) longjmp(env, value)
#endif
#endif
typedef struct { jmp_buf env; } __btrc_try_frame;
static _Thread_local __btrc_try_frame** __btrc_try_stack = NULL;
static _Thread_local char __btrc_error_msg[1024] = "";
/* btrc-runtime-helper:end __btrc_trycatch_globals */
/* btrc-runtime-helper:begin __btrc_copy_error_message */
static inline void __btrc_copy_error_message(
        char* destination, size_t capacity, const char* source) {
    if (!destination || capacity == 0) return;
    if (!source) {
        destination[0] = '\0';
        return;
    }
    size_t length = 0;
    while (length < capacity - 1 && source[length] != '\0') length++;
    memmove(destination, source, length);
    destination[length] = '\0';
}
/* btrc-runtime-helper:end __btrc_copy_error_message */
/* btrc-runtime-helper:begin __btrc_try_capacity */
static _Thread_local int __btrc_try_cap = 16;
/* btrc-runtime-helper:end __btrc_try_capacity */
/* btrc-runtime-helper:begin __btrc_launder_state */
static _Thread_local void* volatile __btrc_launder_slot;
/* btrc-runtime-helper:end __btrc_launder_state */
/* btrc-runtime-helper:begin __btrc_launder */
/* Opaque pointer launder used when returning a freshly-built object
 * out of a try/catch. gcc -O2 (e.g. nix's fortify hardening) runs
 * points-to / store-merging across the setjmp(...)==0 vs catch
 * branches and, for an object that does not otherwise escape, folds
 * the two branches' field inits together -- dropping the catch
 * object's initialization (its fields read back as the other
 * branch's values). Routing the pointer through a volatile slot
 * forces the object to escape, which defeats that miscompilation.
 * Pure C11; the volatile access is the optimization barrier. */
static inline void* __btrc_launder(void* p) {
    __btrc_launder_slot = p;
    return __btrc_launder_slot;
}
/* btrc-runtime-helper:end __btrc_launder */
/* btrc-runtime-helper:begin __btrc_push_try */
static inline void __btrc_push_try(void) {
    if (__btrc_try_cap < 1) __btrc_try_cap = 16;
    if (__btrc_try_top == INT_MAX) { fprintf(stderr, "btrc: try stack overflow\n"); exit(1); }
    if (!__btrc_try_stack) {
        if ((size_t)__btrc_try_cap > SIZE_MAX / sizeof(*__btrc_try_stack)) { fprintf(stderr, "btrc: try stack size overflow\n"); exit(1); }
        __btrc_try_stack = (__btrc_try_frame**)__btrc_safe_realloc(
            NULL, sizeof(*__btrc_try_stack) * (size_t)__btrc_try_cap);
        for (int i = 0; i < __btrc_try_cap; i++) __btrc_try_stack[i] = NULL;
    }
    if (__btrc_try_top + 1 >= __btrc_try_cap) {
        if (__btrc_try_cap > INT_MAX / 2) { fprintf(stderr, "btrc: try stack capacity overflow\n"); exit(1); }
        int old_cap = __btrc_try_cap;
        int new_cap = __btrc_try_cap * 2;
        if ((size_t)new_cap > SIZE_MAX / sizeof(*__btrc_try_stack)) { fprintf(stderr, "btrc: try stack size overflow\n"); exit(1); }
        __btrc_try_stack = (__btrc_try_frame**)__btrc_safe_realloc(
            __btrc_try_stack, sizeof(*__btrc_try_stack) * (size_t)new_cap);
        for (int i = old_cap; i < new_cap; i++) __btrc_try_stack[i] = NULL;
        __btrc_try_cap = new_cap;
    }
    __btrc_try_top++;
    if (!__btrc_try_stack[__btrc_try_top]) {
        __btrc_try_stack[__btrc_try_top] = (__btrc_try_frame*)
            __btrc_safe_realloc(NULL, sizeof(__btrc_try_frame));
    }
}
/* btrc-runtime-helper:end __btrc_push_try */
/* btrc-runtime-helper:begin __btrc_cleanup_types */
/* Cleanup slots are opaque; generated adapters access their exact type. */
typedef __btrc_destroy_fn __btrc_cleanup_fn;
typedef void* (*__btrc_cleanup_take_fn)(void*);
typedef struct { void* slot; __btrc_cleanup_take_fn take; __btrc_cleanup_fn fn; __btrc_visit_fn visit; int try_level; int direct; } __btrc_cleanup_entry;
static _Thread_local __btrc_cleanup_entry* __btrc_cleanup_stack = NULL;
static _Thread_local int __btrc_cleanup_top = -1;
/* btrc-runtime-helper:end __btrc_cleanup_types */
/* btrc-runtime-helper:begin __btrc_cleanup_capacity */
static _Thread_local int __btrc_cleanup_cap = 64;
/* btrc-runtime-helper:end __btrc_cleanup_capacity */
/* btrc-runtime-helper:begin __btrc_register_cleanup_kind */
static inline void __btrc_register_cleanup_kind(
        void* slot, __btrc_cleanup_take_fn take,
        __btrc_cleanup_fn fn, __btrc_visit_fn visit, int direct) {
    if (!slot || !take || !fn) return;
    /* Look for a superseded entry among the most recent registrations only.
     *
     * Finding one is an optimization, not a correctness requirement:
     * __btrc_run_cleanups takes every slot in the batch before running any
     * cleanup, and a take clears the slot it reads, so a duplicate left behind
     * reads back NULL and is skipped. What the search prevents is a slot that
     * is assigned repeatedly -- a loop body, say -- pushing one entry per
     * assignment, and the entry to reuse in that case is the one this scope
     * pushed most recently. Scanning the whole stack to find it made every
     * managed assignment linear in the number of live entries: over a single
     * compile of a thirty-line input, the self-hosted compiler ran 1.54 billion
     * iterations of this loop to serve 41,267 matches, averaging 99.9 iterations
     * per call for a 0.27% hit rate. Entries are never moved, so a window
     * measured down from the top is stable. */
    const int recent = 16;
    int oldest = __btrc_cleanup_top - (recent - 1);
    if (oldest < 0) oldest = 0;
    for (int i = __btrc_cleanup_top; i >= oldest; i--) {
        __btrc_cleanup_entry* existing = &__btrc_cleanup_stack[i];
        if (existing->try_level == __btrc_try_top && existing->slot == slot) {
            existing->take = take;
            existing->fn = fn;
            existing->visit = visit;
            existing->direct = direct;
            return;
        }
    }
    if (__btrc_cleanup_cap < 1) __btrc_cleanup_cap = 64;
    if (!__btrc_cleanup_stack) {
        if ((size_t)__btrc_cleanup_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflow\n"); exit(1); }
        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            NULL, sizeof(__btrc_cleanup_entry) * (size_t)__btrc_cleanup_cap);
    }
    if (__btrc_cleanup_top == INT_MAX) { fprintf(stderr, "btrc: cleanup stack overflow\n"); exit(1); }
    if (__btrc_cleanup_top + 1 >= __btrc_cleanup_cap) {
        if (__btrc_cleanup_cap > INT_MAX / 2) { fprintf(stderr, "btrc: cleanup stack capacity overflow\n"); exit(1); }
        int new_cap = __btrc_cleanup_cap * 2;
        if ((size_t)new_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflow\n"); exit(1); }
        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            __btrc_cleanup_stack, sizeof(__btrc_cleanup_entry) * (size_t)new_cap);
        __btrc_cleanup_cap = new_cap;
    }
    __btrc_cleanup_top++;
    __btrc_cleanup_stack[__btrc_cleanup_top] = (__btrc_cleanup_entry){
        slot, take, fn, visit, __btrc_try_top, direct};
}
/* btrc-runtime-helper:end __btrc_register_cleanup_kind */
/* btrc-runtime-helper:begin __btrc_register_cleanup */
static inline void __btrc_register_cleanup(
        void* slot, __btrc_cleanup_take_fn take,
        __btrc_cleanup_fn fn, __btrc_visit_fn visit) {
    __btrc_register_cleanup_kind(slot, take, fn, visit, 0);
}
/* btrc-runtime-helper:end __btrc_register_cleanup */
/* btrc-runtime-helper:begin __btrc_register_direct_cleanup */
static inline void __btrc_register_direct_cleanup(
        void* slot, __btrc_cleanup_take_fn take, __btrc_cleanup_fn fn) {
    __btrc_register_cleanup_kind(slot, take, fn, NULL, 1);
}
/* btrc-runtime-helper:end __btrc_register_direct_cleanup */
/* btrc-runtime-helper:begin __btrc_run_cleanup_guarded */
static void __btrc_run_cleanup_guarded(
        __btrc_cleanup_entry entry, void* object) {
    __btrc_push_try();
    int guard_level = __btrc_try_top;
    if (BTRC_TRY_SETJMP(__btrc_try_stack[guard_level]->env) != 0) return;
    if (entry.direct) {
        entry.fn(object);
    } else {
        __btrc_arc_type type = {
            .visit = entry.visit, .destroy = entry.fn,
            .hook = NULL, .guard = NULL, .raise = NULL};
        /* The slot metadata is only a fallback. A base-typed slot
         * may hold a cyclic subclass, so the concrete ARC header
         * must choose whether release discovers a cycle. */
        __btrc_arc_release(object, &type);
    }
    __btrc_try_top--;
}
/* btrc-runtime-helper:end __btrc_run_cleanup_guarded */
/* btrc-runtime-helper:begin __btrc_arc_guard_hook */
static int __btrc_arc_guard_hook(
        __btrc_hook_fn hook, void* object,
        char* error, size_t error_capacity) {
    char ambient[sizeof __btrc_error_msg];
    memcpy(ambient, __btrc_error_msg, sizeof ambient);
    if (error && error_capacity) error[0] = '\0';
    __btrc_push_try();
    int guard_level = __btrc_try_top;
    if (BTRC_TRY_SETJMP(__btrc_try_stack[guard_level]->env) != 0) {
        __btrc_copy_error_message(
            error, error_capacity, __btrc_error_msg);
        memcpy(__btrc_error_msg, ambient, sizeof ambient);
        return 1;
    }
    hook(object);
    __btrc_try_top--;
    memcpy(__btrc_error_msg, ambient, sizeof ambient);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_guard_hook */
/* btrc-runtime-helper:begin __btrc_raise_captured */
static _Noreturn void __btrc_raise_captured(
        __btrc_raise_fn raise, const char* message) {
    if (raise) raise(message);
    fprintf(stderr, "Unhandled exception: %s\n", message);
    exit(1);
}
/* btrc-runtime-helper:end __btrc_raise_captured */
/* btrc-runtime-helper:begin __btrc_flush_cycles_guarded */
static void __btrc_flush_cycles_guarded(void) {
    __btrc_push_try();
    int guard_level = __btrc_try_top;
    if (BTRC_TRY_SETJMP(__btrc_try_stack[guard_level]->env) != 0) return;
    __btrc_flush_cycles();
    __btrc_try_top--;
}
/* btrc-runtime-helper:end __btrc_flush_cycles_guarded */
/* btrc-runtime-helper:begin __btrc_run_cleanups */
static inline void __btrc_run_cleanups(int level) {
    int base = __btrc_cleanup_top;
    while (base >= 0 && __btrc_cleanup_stack[base].try_level >= level) base--;
    base++;
    if (base > __btrc_cleanup_top) return;
    int count = __btrc_cleanup_top - base + 1;
    if ((size_t)count > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup batch size overflow\n"); exit(1); }
    __btrc_cleanup_entry* entries = (__btrc_cleanup_entry*)__btrc_safe_realloc(
        NULL, sizeof(__btrc_cleanup_entry) * (size_t)count);
    memcpy(entries, &__btrc_cleanup_stack[base],
        sizeof(__btrc_cleanup_entry) * (size_t)count);
    __btrc_cleanup_top = base - 1;
    if ((size_t)count > SIZE_MAX / sizeof(void*)) { fprintf(stderr, "btrc: cleanup object batch size overflow\n"); exit(1); }
    void** objects = (void**)__btrc_safe_realloc(
        NULL, sizeof(void*) * (size_t)count);
    for (int i = count - 1; i >= 0; i--) {
        __btrc_cleanup_entry entry = entries[i];
        objects[i] = (!entry.fn || !entry.slot || !entry.take)
            ? NULL : entry.take(entry.slot);
    }
    char primary_error[sizeof __btrc_error_msg];
    memcpy(primary_error, __btrc_error_msg, sizeof primary_error);
    __btrc_destroyed_tracking_begin();
    for (int i = count - 1; i >= 0; i--) {
        __btrc_cleanup_entry entry = entries[i];
        void* object = objects[i];
        if (!object) continue;
        if (!entry.direct && __btrc_is_destroyed(object)) continue;
        __btrc_run_cleanup_guarded(entry, object);
        memcpy(__btrc_error_msg, primary_error, sizeof primary_error);
    }
    __btrc_flush_cycles_guarded();
    memcpy(__btrc_error_msg, primary_error, sizeof primary_error);
    __btrc_destroyed_tracking_end();
    free(objects);
    free(entries);
}
/* btrc-runtime-helper:end __btrc_run_cleanups */
/* btrc-runtime-helper:begin __btrc_discard_cleanups */
static inline void __btrc_discard_cleanups(int level) {
    while (__btrc_cleanup_top >= 0 &&
           __btrc_cleanup_stack[__btrc_cleanup_top].try_level >= level) {
        __btrc_cleanup_top--;
    }
}
/* btrc-runtime-helper:end __btrc_discard_cleanups */
/* btrc-runtime-helper:begin __btrc_cleanup_mark */
static inline int __btrc_cleanup_mark(void) { return __btrc_cleanup_top; }
/* btrc-runtime-helper:end __btrc_cleanup_mark */
/* btrc-runtime-helper:begin __btrc_discard_cleanups_to */
static inline void __btrc_discard_cleanups_to(int mark) {
    if (mark < -1 || mark > __btrc_cleanup_top) {
        fprintf(stderr, "btrc: invalid cleanup scope marker\n");
        exit(1);
    }
    __btrc_cleanup_top = mark;
}
/* btrc-runtime-helper:end __btrc_discard_cleanups_to */
/* btrc-runtime-helper:begin __btrc_throw */
static _Noreturn void __btrc_throw(const char* msg) {
    const char* text = msg ? msg : "Unknown exception";
    __btrc_copy_error_message(
        __btrc_error_msg, sizeof __btrc_error_msg, text);
    if (__btrc_try_top < 0) {
        __btrc_run_cleanups(-1);
        fprintf(stderr, "Unhandled exception: %s\n", __btrc_error_msg);
        exit(1);
    }
    __btrc_run_cleanups(__btrc_try_top);
    int level = __btrc_try_top;
    __btrc_try_top--;
    BTRC_TRY_LONGJMP(__btrc_try_stack[level]->env, 1);
}
/* btrc-runtime-helper:end __btrc_throw */
/* btrc-runtime-helper:begin __btrc_try_state_cleanup */
static void __btrc_try_state_cleanup(void) {
    for (int i = 0; i < __btrc_try_cap; i++) {
        free(__btrc_try_stack ? __btrc_try_stack[i] : NULL);
    }
    free(__btrc_try_stack);
    free(__btrc_cleanup_stack);
    __btrc_try_stack = NULL;
    __btrc_cleanup_stack = NULL;
    __btrc_try_cap = 16;
    __btrc_cleanup_cap = 64;
    __btrc_try_top = -1;
    __btrc_cleanup_top = -1;
    __btrc_error_msg[0] = '\0';
    __btrc_launder_slot = NULL;
}
/* btrc-runtime-helper:end __btrc_try_state_cleanup */
