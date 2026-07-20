"""Terminal ARC queue drain and downstream-cycle fixpoint."""

from .core import HelperDef

ARC_DRAIN_HELPERS = {
    "__btrc_arc_drain": HelperDef(
        c_source=r"""static void __btrc_arc_drain_deferred(int force_cycles) {
    if (__btrc_arc_draining) return;
    if (__btrc_arc_topology_depth > 0) {
        __btrc_arc_lock_mutation();
        if (force_cycles || __btrc_arc_deferred_head
                || __btrc_suspect_count > 0)
            __btrc_arc_topology_flush_pending = 1;
        __btrc_arc_unlock_mutation();
        return;
    }
    __btrc_arc_lock_mutation();
    int has_terminal = __btrc_arc_deferred_head != NULL;
    if (!has_terminal && !force_cycles) {
        __btrc_arc_unlock_mutation();
        return;
    }
    if (__btrc_arc_active_drains == INT_MAX) {
        fprintf(stderr, "btrc: ARC drain count overflow\n");
        exit(1);
    }
    __btrc_arc_active_drains++;
    __btrc_arc_unlock_mutation();

    __btrc_arc_draining = 1;
    int cascade = 0;
    char first_error[1024];
    first_error[0] = '\0';
    __btrc_raise_fn first_raise = NULL;
    int has_error = 0;
    for (;;) {
        __btrc_arc_lock_mutation();
        void* object = __btrc_arc_deferred_head;
        if (object) {
            __btrc_arc_header* header = __btrc_arc_header_of(object);
            if (header->state != __BTRC_ARC_QUEUED) {
                fprintf(stderr, "btrc: invalid deferred ARC state\n");
                exit(1);
            }
            __btrc_arc_deferred_head = header->deferred_next;
            if (!__btrc_arc_deferred_head)
                __btrc_arc_deferred_tail = NULL;
            header->deferred_next = NULL;
            int suppress_hook = header->suppress_hook;
            header->suppress_hook = 0;
            header->state = __BTRC_ARC_DESTROYING;
            const __btrc_arc_type* type = header->type;
            __btrc_arc_unlock_mutation();

            if (type->visit || type->hook) cascade = 1;
            if (type->hook && !suppress_hook) {
                char error[1024];
                error[0] = '\0';
                if (type->guard(type->hook, object, error, sizeof error)
                        && !has_error) {
                    memcpy(first_error, error, sizeof first_error);
                    first_raise = type->raise;
                    has_error = 1;
                }
            }
            type->destroy(object);
            continue;
        }
        int pending = __btrc_suspect_count > 0;
        if (!pending && __btrc_arc_topology_active == 0)
            __btrc_arc_topology_flush_pending = 0;
        __btrc_arc_unlock_mutation();
        if (!(pending && (force_cycles || cascade))) break;
        int collected = __btrc_collect_cycles_once();
        if (collected == 1) continue;
        /* Another collector owns the snapshot, or another thread owns a
         * topology scope.  In either case collect-once has published the
         * global flush request.  Never wait here: the topology owner may be
         * waiting for this thread, while an active collector will finish the
         * handoff from its own drain loop. */
        break;
    }
    __btrc_arc_draining = 0;
    __btrc_arc_lock_mutation();
    if (__btrc_arc_active_drains <= 0) {
        fprintf(stderr, "btrc: invalid ARC drain count\n");
        exit(1);
    }
    __btrc_arc_active_drains--;
    __btrc_arc_unlock_mutation();
    if (has_error) {
        __btrc_arc_type transport = {
            .visit = NULL, .destroy = NULL, .hook = NULL,
            .guard = NULL, .raise = first_raise};
        __btrc_arc_raise_unlocked(&transport, first_error);
    }
}""",
        depends_on=[
            "__btrc_arc_deferred_state",
            "__btrc_collect_cycles_once",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_topology_state",
            "__btrc_arc_topology_depth_state",
            "__btrc_arc_shutdown_state",
            "__btrc_arc_active_drains_state",
        ],
        required_headers=["limits.h", "stdio.h", "stdlib.h", "string.h"],
    ),
}

__all__ = ["ARC_DRAIN_HELPERS"]
