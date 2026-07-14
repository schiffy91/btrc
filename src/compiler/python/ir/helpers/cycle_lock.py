"""Process-wide ARC mutation lock and deferred destruction queue."""

from .core import HelperDef

ARC_LOCK_HELPERS = {
    "__btrc_arc_lock_state": HelperDef(
        c_source=r"""/* One process-wide lock domain for ARC topology. */
static atomic_flag __btrc_arc_lock_flag = ATOMIC_FLAG_INIT;

static void __btrc_arc_lock_raw(void) {
    while (atomic_flag_test_and_set_explicit(
            &__btrc_arc_lock_flag, memory_order_acquire)) {}
}
static void __btrc_arc_unlock_raw(void) {
    atomic_flag_clear_explicit(
        &__btrc_arc_lock_flag, memory_order_release);
}""",
        required_headers=["stdatomic.h"],
    ),
    "__btrc_arc_snapshot_state": HelperDef(
        c_source="static _Atomic int __btrc_arc_snapshotting = 0;",
        required_headers=["stdatomic.h"],
    ),
    "__btrc_arc_mutation_lock": HelperDef(
        c_source=r"""static void __btrc_arc_lock_mutation(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire))
            return;
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
}
static void __btrc_arc_unlock_mutation(void) {
    __btrc_arc_unlock_raw();
}""",
        depends_on=["__btrc_arc_lock_state", "__btrc_arc_snapshot_state"],
    ),
    "__btrc_arc_topology_state": HelperDef(
        c_source=("static int __btrc_arc_topology_active = 0;\nstatic int __btrc_arc_topology_flush_pending = 0;"),
    ),
    "__btrc_arc_topology_depth_state": HelperDef(
        c_source="static _Thread_local int __btrc_arc_topology_depth = 0;",
    ),
    "__btrc_arc_topology_begin": HelperDef(
        c_source=r"""static void* __btrc_arc_topology_begin(void) {
    if (__btrc_arc_topology_depth > 0) {
        if (__btrc_arc_topology_depth == INT_MAX) {
            fprintf(stderr, "btrc: ARC topology scope overflow\n");
            exit(1);
        }
        __btrc_arc_topology_depth++;
        return (void*)&__btrc_arc_topology_active;
    }
    for (;;) {
        __btrc_arc_lock_raw();
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)
                && !__btrc_arc_topology_flush_pending) {
            if (__btrc_arc_topology_active == INT_MAX) {
                fprintf(stderr, "btrc: ARC topology scope overflow\n");
                exit(1);
            }
            __btrc_arc_topology_active++;
            __btrc_arc_topology_depth = 1;
            __btrc_arc_unlock_raw();
            return (void*)&__btrc_arc_topology_active;
        }
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
}""",
        depends_on=[
            "__btrc_arc_lock_state",
            "__btrc_arc_snapshot_state",
            "__btrc_arc_topology_state",
            "__btrc_arc_topology_depth_state",
        ],
        required_headers=["limits.h", "stdio.h", "stdlib.h"],
    ),
    "__btrc_arc_topology_leave": HelperDef(
        c_source=r"""static int __btrc_arc_topology_leave(void* token) {
    if (!token) return 0;
    if (token != (void*)&__btrc_arc_topology_active
            || __btrc_arc_topology_depth <= 0) {
        fprintf(stderr, "btrc: invalid ARC topology scope\n");
        exit(1);
    }
    __btrc_arc_topology_depth--;
    if (__btrc_arc_topology_depth > 0) return 0;
    __btrc_arc_lock_raw();
    if (__btrc_arc_topology_active <= 0) {
        fprintf(stderr, "btrc: invalid ARC topology scope\n");
        exit(1);
    }
    __btrc_arc_topology_active--;
    int should_flush = __btrc_arc_topology_active == 0
        && __btrc_arc_topology_flush_pending;
    __btrc_arc_unlock_raw();
    return should_flush;
}""",
        depends_on=[
            "__btrc_arc_lock_state",
            "__btrc_arc_topology_state",
            "__btrc_arc_topology_depth_state",
        ],
        required_headers=["stdio.h", "stdlib.h"],
    ),
    "__btrc_arc_topology_cleanup": HelperDef(
        c_source=(
            "static void __btrc_arc_topology_cleanup(void* token) {\n    (void)__btrc_arc_topology_leave(token);\n}"
        ),
        depends_on=["__btrc_arc_topology_leave"],
    ),
    "__btrc_arc_topology_complete": HelperDef(
        c_source=r"""static void __btrc_arc_topology_complete(void** token_ref) {
    if (!token_ref || !*token_ref) return;
    void* token = *token_ref;
    *token_ref = NULL;
    if (__btrc_arc_topology_leave(token))
        (void)__btrc_flush_cycles();
}""",
        depends_on=[
            "__btrc_arc_topology_leave",
            "__btrc_flush_cycles",
        ],
    ),
    "__btrc_arc_deferred_state": HelperDef(
        c_source=r"""typedef struct {
    void* object;
    __btrc_destroy_fn destroy;
} __btrc_arc_deferred;
static __btrc_arc_deferred* __btrc_arc_deferred_items = NULL;
static int __btrc_arc_deferred_count = 0;
static int __btrc_arc_deferred_cap = 0;

static void __btrc_arc_defer_destroy_locked(
        void* object, __btrc_destroy_fn destroy) {
    if (__btrc_arc_deferred_count >= __btrc_arc_deferred_cap) {
        if (__btrc_arc_deferred_cap > INT_MAX / 2) {
            fprintf(stderr, "btrc: deferred ARC queue overflow\n");
            exit(1);
        }
        int cap = __btrc_arc_deferred_cap
            ? __btrc_arc_deferred_cap * 2 : 256;
        __btrc_arc_deferred_items = (__btrc_arc_deferred*)
            __btrc_safe_realloc(__btrc_arc_deferred_items,
                sizeof(__btrc_arc_deferred) * (size_t)cap);
        __btrc_arc_deferred_cap = cap;
    }
    __btrc_arc_deferred_items[__btrc_arc_deferred_count++] =
        (__btrc_arc_deferred){object, destroy};
}
static void __btrc_arc_drain_deferred(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_deferred_count == 0) {
            __btrc_arc_unlock_raw();
            return;
        }
        __btrc_arc_deferred item =
            __btrc_arc_deferred_items[--__btrc_arc_deferred_count];
        __btrc_arc_unlock_raw();
        item.destroy(item.object);
    }
}""",
        depends_on=[
            "__btrc_arc_callback_types",
            "__btrc_arc_lock_state",
            "__btrc_safe_realloc",
        ],
    ),
}

__all__ = ["ARC_LOCK_HELPERS"]
