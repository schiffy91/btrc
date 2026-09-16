/* btrc-runtime-helper:begin __btrc_tls_state */
/* Every per-thread runtime variable lives in one thread-local record. A
 * separate _Thread_local object costs its own address lookup on targets that
 * resolve thread storage out of line (Darwin's _tlv_get_addr): a cleanup
 * registration touched four of them, and those lookups were a quarter of the
 * self-hosted compiler's time. The C compiler folds every access to one record
 * into a single lookup per function. Runtime helpers, generated code and
 * cross-unit fixtures name the record's fields directly. */
typedef struct {
    volatile int try_top;
    struct __btrc_try_frame** try_stack;
    char error_msg[1024];
    int try_cap;
    void* volatile launder_slot;
    struct __btrc_cleanup_entry* cleanup_stack;
    int cleanup_top;
    int cleanup_cap;
    int tracking;
    void** destroyed;
    int destroyed_count;
    int destroyed_cap;
    int arc_topology_depth;
    int arc_draining;
    void* arc_deferred_head;
    void* arc_deferred_tail;
    void (*abandon_drain_callback)(void);
    void** abandon_queue;
    int abandon_count;
    int abandon_cap;
} __btrc_tls_record;
static _Thread_local __btrc_tls_record __btrc_tls = {
    .try_top = -1, .try_cap = 16, .cleanup_top = -1, .cleanup_cap = 64};
/* btrc-runtime-helper:end __btrc_tls_state */
/* btrc-runtime-helper:begin __btrc_try_level */
/* __btrc_tls.try_top lives in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_try_level */
/* btrc-runtime-helper:begin __btrc_trycatch_globals */
/* btrc try/catch runtime (dynamic) */
#if defined(__APPLE__) && __STDC_HOSTED__
/* Darwin's setjmp saves the signal mask and the alternate-stack state, two
 * system calls on every try frame, cleanup guard and deferred drain. A btrc
 * frame never changes either, so the BSD register-only variants serve; on
 * glibc, setjmp already is the register-only form. */
#undef setjmp
#undef longjmp
#define setjmp(env) _setjmp(env)
#define longjmp(env, value) _longjmp(env, value)
#endif
typedef struct __btrc_try_frame { jmp_buf env; } __btrc_try_frame;
/* __btrc_tls.try_stack and __btrc_tls.error_msg live in the thread-local record __btrc_tls. */
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
/* __btrc_tls.try_cap lives in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_try_capacity */
/* btrc-runtime-helper:begin __btrc_launder_state */
/* __btrc_tls.launder_slot lives in the thread-local record __btrc_tls. */
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
    __btrc_tls.launder_slot = p;
    return __btrc_tls.launder_slot;
}
/* btrc-runtime-helper:end __btrc_launder */
/* btrc-runtime-helper:begin __btrc_push_try */
static inline void __btrc_push_try(void) {
    if (__btrc_tls.try_cap < 1) __btrc_tls.try_cap = 16;
    if (__btrc_tls.try_top == INT_MAX) { fprintf(stderr, "btrc: try stack overflow\n"); exit(1); }
    if (!__btrc_tls.try_stack) {
        if ((size_t)__btrc_tls.try_cap > SIZE_MAX / sizeof(*__btrc_tls.try_stack)) { fprintf(stderr, "btrc: try stack size overflow\n"); exit(1); }
        __btrc_tls.try_stack = (__btrc_try_frame**)__btrc_safe_realloc(
            NULL, sizeof(*__btrc_tls.try_stack) * (size_t)__btrc_tls.try_cap);
        for (int i = 0; i < __btrc_tls.try_cap; i++) __btrc_tls.try_stack[i] = NULL;
    }
    if (__btrc_tls.try_top + 1 >= __btrc_tls.try_cap) {
        if (__btrc_tls.try_cap > INT_MAX / 2) { fprintf(stderr, "btrc: try stack capacity overflow\n"); exit(1); }
        int old_cap = __btrc_tls.try_cap;
        int new_cap = __btrc_tls.try_cap * 2;
        if ((size_t)new_cap > SIZE_MAX / sizeof(*__btrc_tls.try_stack)) { fprintf(stderr, "btrc: try stack size overflow\n"); exit(1); }
        __btrc_tls.try_stack = (__btrc_try_frame**)__btrc_safe_realloc(
            __btrc_tls.try_stack, sizeof(*__btrc_tls.try_stack) * (size_t)new_cap);
        for (int i = old_cap; i < new_cap; i++) __btrc_tls.try_stack[i] = NULL;
        __btrc_tls.try_cap = new_cap;
    }
    __btrc_tls.try_top++;
    if (!__btrc_tls.try_stack[__btrc_tls.try_top]) {
        __btrc_tls.try_stack[__btrc_tls.try_top] = (__btrc_try_frame*)
            __btrc_safe_realloc(NULL, sizeof(__btrc_try_frame));
    }
}
/* btrc-runtime-helper:end __btrc_push_try */
/* btrc-runtime-helper:begin __btrc_cleanup_types */
/* Cleanup slots are opaque; generated adapters access their exact type. */
typedef __btrc_destroy_fn __btrc_cleanup_fn;
typedef void* (*__btrc_cleanup_take_fn)(void*);
typedef struct __btrc_cleanup_entry { void* slot; __btrc_cleanup_take_fn take; __btrc_cleanup_fn fn; __btrc_visit_fn visit; int try_level; int direct; } __btrc_cleanup_entry;
/* __btrc_tls.cleanup_stack and __btrc_tls.cleanup_top live in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_cleanup_types */
/* btrc-runtime-helper:begin __btrc_cleanup_capacity */
/* __btrc_tls.cleanup_cap lives in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_cleanup_capacity */
/* btrc-runtime-helper:begin __btrc_register_cleanup_kind */
static inline void __btrc_register_cleanup_kind(
        void* slot, __btrc_cleanup_take_fn take,
        __btrc_cleanup_fn fn, __btrc_visit_fn visit, int direct) {
    if (!slot || !take || (direct && !fn)) return;
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
     * measured down from the top is stable. Four entries catch the loop-body
     * case; a wider window only made the misses, which are the common case,
     * proportionally slower (the scan was a sixth of the self-hosted
     * compiler's time at sixteen). */
    /* Each _Thread_local read is an out-of-line call on some targets, so read
     * the ones this path needs once. The reallocating branch below refreshes
     * `stack`, which is the only local a resize can invalidate. */
    const int recent = 4;
    const int try_level = __btrc_tls.try_top;
    int top = __btrc_tls.cleanup_top;
    __btrc_cleanup_entry* stack = __btrc_tls.cleanup_stack;
    int oldest = top - (recent - 1);
    if (oldest < 0) oldest = 0;
    for (int i = top; i >= oldest; i--) {
        __btrc_cleanup_entry* existing = &stack[i];
        if (existing->try_level == try_level && existing->slot == slot) {
            existing->take = take;
            existing->fn = fn;
            existing->visit = visit;
            existing->direct = direct;
            return;
        }
    }
    if (__btrc_tls.cleanup_cap < 1) __btrc_tls.cleanup_cap = 64;
    if (!stack) {
        if ((size_t)__btrc_tls.cleanup_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflow\n"); exit(1); }
        stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            NULL, sizeof(__btrc_cleanup_entry) * (size_t)__btrc_tls.cleanup_cap);
        __btrc_tls.cleanup_stack = stack;
    }
    if (top == INT_MAX) { fprintf(stderr, "btrc: cleanup stack overflow\n"); exit(1); }
    if (top + 1 >= __btrc_tls.cleanup_cap) {
        if (__btrc_tls.cleanup_cap > INT_MAX / 2) { fprintf(stderr, "btrc: cleanup stack capacity overflow\n"); exit(1); }
        int new_cap = __btrc_tls.cleanup_cap * 2;
        if ((size_t)new_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflow\n"); exit(1); }
        stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            stack, sizeof(__btrc_cleanup_entry) * (size_t)new_cap);
        __btrc_tls.cleanup_stack = stack;
        __btrc_tls.cleanup_cap = new_cap;
    }
    top++;
    __btrc_tls.cleanup_top = top;
    stack[top] = (__btrc_cleanup_entry){
        slot, take, fn, visit, try_level, direct};
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
    int guard_level = __btrc_tls.try_top;
    if (setjmp(__btrc_tls.try_stack[guard_level]->env) != 0) return;
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
    __btrc_tls.try_top--;
}
/* btrc-runtime-helper:end __btrc_run_cleanup_guarded */
/* btrc-runtime-helper:begin __btrc_arc_guard_hook */
static int __btrc_arc_guard_hook(
        __btrc_hook_fn hook, void* object,
        char* error, size_t error_capacity) {
    char ambient[sizeof __btrc_tls.error_msg];
    memcpy(ambient, __btrc_tls.error_msg, sizeof ambient);
    if (error && error_capacity) error[0] = '\0';
    __btrc_push_try();
    int guard_level = __btrc_tls.try_top;
    if (setjmp(__btrc_tls.try_stack[guard_level]->env) != 0) {
        __btrc_copy_error_message(
            error, error_capacity, __btrc_tls.error_msg);
        memcpy(__btrc_tls.error_msg, ambient, sizeof ambient);
        return 1;
    }
    hook(object);
    __btrc_tls.try_top--;
    memcpy(__btrc_tls.error_msg, ambient, sizeof ambient);
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
    int guard_level = __btrc_tls.try_top;
    if (setjmp(__btrc_tls.try_stack[guard_level]->env) != 0) return;
    __btrc_flush_cycles();
    __btrc_tls.try_top--;
}
/* btrc-runtime-helper:end __btrc_flush_cycles_guarded */
/* btrc-runtime-helper:begin __btrc_run_cleanups */
static inline void __btrc_run_cleanups(int level) {
    int base = __btrc_tls.cleanup_top;
    while (base >= 0 && __btrc_tls.cleanup_stack[base].try_level >= level) base--;
    base++;
    if (base > __btrc_tls.cleanup_top) return;
    int count = __btrc_tls.cleanup_top - base + 1;
    if ((size_t)count > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup batch size overflow\n"); exit(1); }
    __btrc_cleanup_entry* entries = (__btrc_cleanup_entry*)__btrc_safe_realloc(
        NULL, sizeof(__btrc_cleanup_entry) * (size_t)count);
    memcpy(entries, &__btrc_tls.cleanup_stack[base],
        sizeof(__btrc_cleanup_entry) * (size_t)count);
    __btrc_tls.cleanup_top = base - 1;
    if ((size_t)count > SIZE_MAX / sizeof(void*)) { fprintf(stderr, "btrc: cleanup object batch size overflow\n"); exit(1); }
    void** objects = (void**)__btrc_safe_realloc(
        NULL, sizeof(void*) * (size_t)count);
    for (int i = count - 1; i >= 0; i--) {
        __btrc_cleanup_entry entry = entries[i];
        objects[i] = ((entry.direct && !entry.fn) || !entry.slot || !entry.take)
            ? NULL : entry.take(entry.slot);
    }
    char primary_error[sizeof __btrc_tls.error_msg];
    memcpy(primary_error, __btrc_tls.error_msg, sizeof primary_error);
    __btrc_destroyed_tracking_begin();
    for (int i = count - 1; i >= 0; i--) {
        __btrc_cleanup_entry entry = entries[i];
        void* object = objects[i];
        if (!object) continue;
        if (!entry.direct && __btrc_is_destroyed(object)) continue;
        __btrc_run_cleanup_guarded(entry, object);
        memcpy(__btrc_tls.error_msg, primary_error, sizeof primary_error);
    }
    __btrc_flush_cycles_guarded();
    memcpy(__btrc_tls.error_msg, primary_error, sizeof primary_error);
    __btrc_destroyed_tracking_end();
    free(objects);
    free(entries);
}
/* btrc-runtime-helper:end __btrc_run_cleanups */
/* btrc-runtime-helper:begin __btrc_discard_cleanups */
static inline void __btrc_discard_cleanups(int level) {
    while (__btrc_tls.cleanup_top >= 0 &&
           __btrc_tls.cleanup_stack[__btrc_tls.cleanup_top].try_level >= level) {
        __btrc_tls.cleanup_top--;
    }
}
/* btrc-runtime-helper:end __btrc_discard_cleanups */
/* btrc-runtime-helper:begin __btrc_cleanup_mark */
static inline int __btrc_cleanup_mark(void) { return __btrc_tls.cleanup_top; }
/* btrc-runtime-helper:end __btrc_cleanup_mark */
/* btrc-runtime-helper:begin __btrc_discard_cleanups_to */
static inline void __btrc_discard_cleanups_to(int mark) {
    if (mark < -1 || mark > __btrc_tls.cleanup_top) {
        fprintf(stderr, "btrc: invalid cleanup scope marker\n");
        exit(1);
    }
    __btrc_tls.cleanup_top = mark;
}
/* btrc-runtime-helper:end __btrc_discard_cleanups_to */
/* btrc-runtime-helper:begin __btrc_throw */
static _Noreturn void __btrc_throw(const char* msg) {
    const char* text = msg ? msg : "Unknown exception";
    __btrc_copy_error_message(
        __btrc_tls.error_msg, sizeof __btrc_tls.error_msg, text);
    if (__btrc_tls.try_top < 0) {
        __btrc_run_cleanups(-1);
        fprintf(stderr, "Unhandled exception: %s\n", __btrc_tls.error_msg);
        exit(1);
    }
    __btrc_run_cleanups(__btrc_tls.try_top);
    int level = __btrc_tls.try_top;
    __btrc_tls.try_top--;
    longjmp(__btrc_tls.try_stack[level]->env, 1);
}
/* btrc-runtime-helper:end __btrc_throw */
/* btrc-runtime-helper:begin __btrc_try_state_cleanup */
static void __btrc_try_state_cleanup(void) {
    for (int i = 0; i < __btrc_tls.try_cap; i++) {
        free(__btrc_tls.try_stack ? __btrc_tls.try_stack[i] : NULL);
    }
    free(__btrc_tls.try_stack);
    free(__btrc_tls.cleanup_stack);
    __btrc_tls.try_stack = NULL;
    __btrc_tls.cleanup_stack = NULL;
    __btrc_tls.try_cap = 16;
    __btrc_tls.cleanup_cap = 64;
    __btrc_tls.try_top = -1;
    __btrc_tls.cleanup_top = -1;
    __btrc_tls.error_msg[0] = '\0';
    __btrc_tls.launder_slot = NULL;
}
/* btrc-runtime-helper:end __btrc_try_state_cleanup */
