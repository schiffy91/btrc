"""Exclusive graph-snapshot admission for synchronous ARC operations."""

from .core import HelperDef

ARC_SNAPSHOT_HELPERS = {
    "__btrc_arc_snapshot_gate_state": HelperDef(
        c_source=(
            "/* Publish snapshot intent before waiting for topology owners. */\n"
            "static _Atomic int __btrc_arc_snapshot_pending = 0;"
        ),
        required_headers=["stdatomic.h"],
    ),
    "__btrc_arc_exclusive_snapshot": HelperDef(
        c_source=r"""static void __btrc_arc_exclusive_snapshot_begin(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (__btrc_arc_topology_depth != 0) {
            fprintf(stderr, "btrc: ARC snapshot inside topology mutation\n");
            exit(1);
        }
        if (!atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                && !atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {
            atomic_store_explicit(
                &__btrc_arc_snapshot_pending, 1, memory_order_release);
            __btrc_arc_unlock_raw();
            break;
        }
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (__btrc_arc_topology_active == 0) {
            atomic_store_explicit(
                &__btrc_arc_snapshotting, 1, memory_order_release);
            atomic_store_explicit(
                &__btrc_arc_snapshot_pending, 0, memory_order_release);
            __btrc_arc_unlock_raw();
            return;
        }
        __btrc_arc_unlock_raw();
    }
}

static void __btrc_arc_exclusive_snapshot_end(void) {
    __btrc_arc_lock_raw();
    if (!atomic_load_explicit(
            &__btrc_arc_snapshotting, memory_order_acquire)) {
        fprintf(stderr, "btrc: invalid ARC snapshot completion\n");
        exit(1);
    }
    atomic_store_explicit(
        &__btrc_arc_snapshotting, 0, memory_order_release);
    __btrc_arc_unlock_raw();
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
}


__all__ = ["ARC_SNAPSHOT_HELPERS"]
