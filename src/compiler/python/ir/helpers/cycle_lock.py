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
    "__btrc_arc_shutdown_state": HelperDef(
        c_source="static int __btrc_arc_shutdown = 0;",
    ),
    "__btrc_arc_active_drains_state": HelperDef(
        c_source="static int __btrc_arc_active_drains = 0;",
    ),
    "__btrc_arc_active_unwinds_state": HelperDef(
        c_source="static int __btrc_arc_active_unwinds = 0;",
    ),
    "__btrc_arc_snapshot_state": HelperDef(
        c_source="static _Atomic int __btrc_arc_snapshotting = 0;",
        required_headers=["stdatomic.h"],
    ),
    "__btrc_arc_mutation_lock": HelperDef(
        c_source=r"""static void __btrc_arc_lock_mutation(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
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
        depends_on=[
            "__btrc_arc_lock_state",
            "__btrc_arc_snapshot_state",
            "__btrc_arc_shutdown_state",
        ],
    ),
    "__btrc_arc_topology_state": HelperDef(
        c_source=("static int __btrc_arc_topology_active = 0;\nstatic int __btrc_arc_topology_flush_pending = 0;"),
    ),
    "__btrc_arc_topology_depth_state": HelperDef(
        c_source=(
            "static _Thread_local int __btrc_arc_topology_depth = 0;\nstatic _Thread_local int __btrc_arc_draining = 0;"
        ),
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
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)
                && !atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                && (!__btrc_arc_topology_flush_pending
                    || __btrc_arc_draining)) {
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
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
}""",
        depends_on=[
            "__btrc_arc_lock_state",
            "__btrc_arc_snapshot_state",
            "__btrc_arc_snapshot_gate_state",
            "__btrc_arc_shutdown_state",
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
    if (__btrc_arc_shutdown) {
        __btrc_arc_unlock_raw();
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
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
            "__btrc_arc_shutdown_state",
            "__btrc_arc_topology_state",
            "__btrc_arc_topology_depth_state",
        ],
        required_headers=["stdio.h", "stdlib.h"],
    ),
    "__btrc_arc_topology_cleanup": HelperDef(
        c_source=r"""static void __btrc_arc_topology_cleanup(void* token) {
    int should_flush = __btrc_arc_topology_leave(token);
    __btrc_arc_drain_pending_abandons();
    if (should_flush)
        (void)__btrc_flush_cycles();
    __btrc_arc_drain_deferred(0);
}""",
        depends_on=[
            "__btrc_arc_topology_leave",
            "__btrc_arc_abandon_queue_drain",
            "__btrc_flush_cycles",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_topology_complete": HelperDef(
        c_source=r"""static void __btrc_arc_topology_complete(
        void* volatile* token_ref) {
    if (!token_ref || !*token_ref) return;
    void* token = *token_ref;
    *token_ref = NULL;
    int should_flush = __btrc_arc_topology_leave(token);
    __btrc_arc_drain_pending_abandons();
    if (should_flush)
        (void)__btrc_flush_cycles();
    __btrc_arc_drain_deferred(0);
}""",
        depends_on=[
            "__btrc_arc_topology_leave",
            "__btrc_arc_abandon_queue_drain",
            "__btrc_flush_cycles",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_deferred_state": HelperDef(
        c_source=r"""/* Per-thread intrusive FIFO for terminal ARC work. */
static _Thread_local void* __btrc_arc_deferred_head = NULL;
static _Thread_local void* __btrc_arc_deferred_tail = NULL;

static _Noreturn void __btrc_arc_raise_unlocked(
        const __btrc_arc_type* type, const char* message) {
    if (type && type->raise) type->raise(message);
    fprintf(stderr, "Unhandled exception: %s\n", message);
    exit(1);
}

static void __btrc_arc_enqueue_locked(void* object) {
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE
            || header->rc != 0 || header->edge_rc != 0
            || header->incoming != NULL || header->deferred_next != NULL) {
        fprintf(stderr, "btrc: invalid ARC enqueue\n");
        exit(1);
    }
    header->live_witness = NULL;
    header->state = __BTRC_ARC_QUEUED;
    if (__btrc_arc_deferred_tail) {
        __btrc_arc_header_of(__btrc_arc_deferred_tail)->deferred_next = object;
    } else {
        __btrc_arc_deferred_head = object;
    }
    __btrc_arc_deferred_tail = object;
}""",
        depends_on=[
            "__btrc_arc_callback_types",
            "__btrc_arc_header_of",
        ],
        required_headers=["stdio.h", "stdlib.h"],
    ),
}

__all__ = ["ARC_LOCK_HELPERS"]
