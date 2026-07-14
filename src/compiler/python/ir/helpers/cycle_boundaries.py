"""Cycle poll, forced-drain, and terminal runtime-state boundaries."""

from .core import HelperDef

CYCLE_BOUNDARY_HELPERS = {
    "__btrc_poll_cycles": HelperDef(
        c_source=(
            "static inline int __btrc_poll_cycles(void) {\n"
            "    __btrc_arc_lock_mutation();\n"
            "    int pending = __btrc_suspect_count >= 256;\n"
            "    __btrc_arc_unlock_mutation();\n"
            "    if (pending) __btrc_collect_cycles();\n"
            "    return 0;\n"
            "}"
        ),
        depends_on=["__btrc_collect_cycles", "__btrc_arc_mutation_lock"],
    ),
    "__btrc_flush_cycles": HelperDef(
        c_source=(
            "static int __btrc_flush_cycles(void) {\n"
            "    for (;;) {\n"
            "        __btrc_arc_lock_mutation();\n"
            "        int pending = __btrc_suspect_count > 0;\n"
            "        int blocked = __btrc_arc_topology_active > 0;\n"
            "        if (pending && blocked)\n"
            "            __btrc_arc_topology_flush_pending = 1;\n"
            "        if (!pending)\n"
            "            __btrc_arc_topology_flush_pending = 0;\n"
            "        __btrc_arc_unlock_mutation();\n"
            "        if (!pending || blocked) return 0;\n"
            "        __btrc_collect_cycles();\n"
            "    }\n"
            "}"
        ),
        depends_on=[
            "__btrc_collect_cycles",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_topology_state",
        ],
    ),
    "__btrc_cycle_state_cleanup": HelperDef(
        c_source=(
            "static inline void __btrc_cycle_state_cleanup(void) {\n"
            "    __btrc_flush_cycles();\n"
            "    __btrc_arc_drain_deferred();\n"
            "    __btrc_arc_lock_mutation();\n"
            "    if (__btrc_arc_topology_active != 0) {\n"
            '        fprintf(stderr, "btrc: ARC cleanup during topology mutation\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    if (atomic_load_explicit(\n"
            "            &__btrc_tracking, memory_order_acquire) != 0) {\n"
            '        fprintf(stderr, "btrc: ARC cleanup during active unwind\\n");\n'
            "        exit(1);\n"
            "    }\n"
            "    free(__btrc_suspects);\n"
            "    free(__btrc_visit_table);\n"
            "    free(__btrc_destroy_table);\n"
            "    free(__btrc_suspect_keys);\n"
            "    free(__btrc_destroyed);\n"
            "    free(__btrc_reverse_queue);\n"
            "    free(__btrc_reverse_keys);\n"
            "    free(__btrc_reverse_marks);\n"
            "    free(__btrc_arc_deferred_items);\n"
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
            "    __btrc_destroyed = NULL;\n"
            "    __btrc_reverse_queue = NULL;\n"
            "    __btrc_reverse_keys = NULL;\n"
            "    __btrc_reverse_marks = NULL;\n"
            "    __btrc_arc_deferred_items = NULL;\n"
            "    __btrc_suspect_count = __btrc_suspect_cap = 0;\n"
            "    __btrc_suspect_key_cap = 0;\n"
            "    __btrc_destroyed_count = __btrc_destroyed_cap = 0;\n"
            "    __btrc_reverse_queue_cap = __btrc_reverse_key_cap = 0;\n"
            "    __btrc_reverse_count = 0;\n"
            "    __btrc_reverse_epoch = 0;\n"
            "    __btrc_arc_deferred_count = __btrc_arc_deferred_cap = 0;\n"
            "    __btrc_arc_topology_flush_pending = 0;\n"
            "    __btrc_collecting = 0;\n"
            "    __btrc_arc_unlock_mutation();\n"
            "}"
        ),
        depends_on=[
            "__btrc_flush_cycles",
            "__btrc_suspect_capacity",
            "__btrc_destroyed_tracking",
            "__btrc_destroyed_capacity",
            "__btrc_arc_reverse_state",
            "__btrc_arc_deferred_state",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_topology_state",
        ],
    ),
}

__all__ = ["CYCLE_BOUNDARY_HELPERS"]
