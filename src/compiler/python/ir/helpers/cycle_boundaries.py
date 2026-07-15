"""Cycle poll, forced-drain, and terminal runtime-state boundaries."""

from .core import HelperDef

CYCLE_BOUNDARY_HELPERS = {
    "__btrc_collect_cycles": HelperDef(
        c_source=("static void __btrc_collect_cycles(void) {\n    __btrc_arc_drain_deferred(1);\n}"),
        depends_on=["__btrc_arc_drain"],
    ),
    "__btrc_poll_cycles": HelperDef(
        c_source=(
            "static inline int __btrc_poll_cycles(void) {\n"
            "    __btrc_arc_lock_mutation();\n"
            "    int pending = __btrc_suspect_count >= 256;\n"
            "    __btrc_arc_unlock_mutation();\n"
            "    if (pending) __btrc_arc_drain_deferred(1);\n"
            "    return 0;\n"
            "}"
        ),
        depends_on=["__btrc_arc_drain", "__btrc_arc_mutation_lock"],
    ),
    "__btrc_flush_cycles": HelperDef(
        c_source=("static int __btrc_flush_cycles(void) {\n    __btrc_arc_drain_deferred(1);\n    return 0;\n}"),
        depends_on=["__btrc_arc_drain"],
    ),
    "__btrc_arc_thread_state_cleanup": HelperDef(
        c_source=(
            "static void __btrc_arc_thread_state_finalize(void) {\n"
            "    __btrc_arc_lock_mutation();\n"
            "    if (__btrc_tracking != 0\n"
            "            || __btrc_arc_topology_depth != 0\n"
            "            || __btrc_arc_draining\n"
            "            || __btrc_arc_deferred_head\n"
            "            || __btrc_arc_deferred_tail\n"
            "            || __btrc_abandon_queue\n"
            "            || __btrc_abandon_count != 0\n"
            "            || __btrc_abandon_drain_callback) {\n"
            '        fprintf(stderr, "btrc: ARC thread cleanup during active work\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    free(__btrc_destroyed);\n"
            "    __btrc_destroyed = NULL;\n"
            "    __btrc_destroyed_count = 0;\n"
            "    __btrc_destroyed_cap = 0;\n"
            "    free(__btrc_abandon_queue);\n"
            "    __btrc_abandon_queue = NULL;\n"
            "    __btrc_abandon_count = 0;\n"
            "    __btrc_abandon_cap = 0;\n"
            "    __btrc_abandon_drain_callback = NULL;\n"
            "    __btrc_arc_unlock_mutation();\n"
            "}\n"
            "static void __btrc_arc_thread_state_cleanup(void) {\n"
            "    __btrc_arc_drain_pending_abandons();\n"
            "    __btrc_arc_drain_deferred(1);\n"
            "    __btrc_arc_thread_state_finalize();\n"
            "}"
        ),
        depends_on=[
            "__btrc_arc_abandon_queue_state",
            "__btrc_arc_abandon_queue_drain",
            "__btrc_arc_drain",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_topology_depth_state",
            "__btrc_arc_deferred_state",
            "__btrc_destroyed_tracking",
            "__btrc_destroyed_capacity",
        ],
    ),
    "__btrc_cycle_state_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_cycle_state_cleanup(void) {\n"
            "    __btrc_arc_thread_state_cleanup();\n"
            "    __btrc_flush_cycles();\n"
            "    __btrc_arc_lock_raw();\n"
            "    if (__btrc_arc_shutdown) {\n"
            "        __btrc_arc_unlock_raw();\n"
            '        fprintf(stderr, "btrc: repeated ARC shutdown\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    __btrc_arc_shutdown = 1;\n"
            "    if (__btrc_arc_active_drains != 0\n"
            "            || __btrc_arc_active_unwinds != 0\n"
            "            || atomic_load_explicit(\n"
            "                &__btrc_arc_snapshotting, memory_order_acquire) != 0\n"
            "            || atomic_load_explicit(\n"
            "                &__btrc_arc_snapshot_pending, memory_order_acquire) != 0\n"
            "            || __btrc_collecting != 0) {\n"
            '        fprintf(stderr, "btrc: ARC cleanup during active work\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    if (__btrc_arc_topology_active != 0) {\n"
            '        fprintf(stderr, "btrc: ARC cleanup during topology mutation\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    free(__btrc_suspects);\n"
            "    free(__btrc_visit_table);\n"
            "    free(__btrc_destroy_table);\n"
            "    free(__btrc_suspect_keys);\n"
            "    free(__btrc_reverse_queue);\n"
            "    free(__btrc_reverse_keys);\n"
            "    free(__btrc_reverse_marks);\n"
            "    free(__btrc_cycle_scratch.vertices);\n"
            "    free(__btrc_cycle_scratch.edges);\n"
            "    free(__btrc_cycle_scratch.queue);\n"
            "    free(__btrc_cycle_scratch.object_keys);\n"
            "    free(__btrc_cycle_scratch.object_values);\n"
            "    free(__btrc_cycle_scratch.object_marks);\n"
            "    free(__btrc_cycle_scratch.slot_keys);\n"
            "    free(__btrc_cycle_scratch.slot_values);\n"
            "    free(__btrc_cycle_scratch.slot_marks);\n"
            "    memset(&__btrc_cycle_scratch, 0, sizeof(__btrc_cycle_scratch));\n"
            "    __btrc_suspects = NULL;\n"
            "    __btrc_visit_table = NULL;\n"
            "    __btrc_destroy_table = NULL;\n"
            "    __btrc_suspect_keys = NULL;\n"
            "    __btrc_reverse_queue = NULL;\n"
            "    __btrc_reverse_keys = NULL;\n"
            "    __btrc_reverse_marks = NULL;\n"
            "    __btrc_suspect_count = __btrc_suspect_cap = 0;\n"
            "    __btrc_suspect_key_cap = 0;\n"
            "    __btrc_reverse_queue_cap = __btrc_reverse_key_cap = 0;\n"
            "    __btrc_reverse_count = 0;\n"
            "    __btrc_reverse_epoch = 0;\n"
            "    if (__btrc_arc_deferred_head || __btrc_arc_deferred_tail\n"
            "            || __btrc_arc_draining) {\n"
            '        fprintf(stderr, "btrc: ARC cleanup during active drain\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    __btrc_arc_topology_flush_pending = 0;\n"
            "    __btrc_collecting = 0;\n"
            "    __btrc_arc_unlock_raw();\n"
            "}"
        ),
        depends_on=[
            "__btrc_flush_cycles",
            "__btrc_arc_thread_state_cleanup",
            "__btrc_suspect_capacity",
            "__btrc_arc_reverse_state",
            "__btrc_arc_deferred_state",
            "__btrc_arc_drain",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_lock_state",
            "__btrc_arc_snapshot_state",
            "__btrc_arc_snapshot_gate_state",
            "__btrc_arc_shutdown_state",
            "__btrc_arc_active_drains_state",
            "__btrc_arc_active_unwinds_state",
            "__btrc_arc_topology_state",
            "__btrc_cycle_collector_state",
        ],
    ),
}

__all__ = ["CYCLE_BOUNDARY_HELPERS"]
