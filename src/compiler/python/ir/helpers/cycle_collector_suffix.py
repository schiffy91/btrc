"""Snapshot, liveness, and reclaim half of the cycle-collector C runtime."""

CYCLE_COLLECTOR_SUFFIX = r"""static void __btrc_cycle_snapshot_edge(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access,
        const __btrc_arc_type* type, void* opaque) {
    __btrc_cycle_context* context = (__btrc_cycle_context*)opaque;
    if (!slot_storage || !access) return;
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) return;
    if (__btrc_cycle_find_slot(context, slot_storage) >= 0) return;
    if (context->slot_cap == 0
            || context->edge_count >= context->slot_cap / 2)
        __btrc_cycle_grow_slots(context);
    int target = __btrc_cycle_add_object(context, object, type);
    if (context->vertices[target].internal == INT_MAX)
        __btrc_cycle_fail("cycle incoming-edge overflow");
    context->vertices[target].internal++;
    __btrc_cycle_vertex* target_vertex = &context->vertices[target];
    if (target_vertex->state == 0) {
        __btrc_arc_header* header =
            __btrc_arc_header_of(target_vertex->object);
        if (header->rc > header->edge_rc) {
            target_vertex->state = 2;
            target_vertex->live = 1;
        } else {
            target_vertex->state = 3;
            __btrc_cycle_push_queue(context, target);
        }
    }
    if (context->edge_count < 0 || context->edge_count == INT_MAX)
        __btrc_cycle_fail("cycle edge overflow");
    __btrc_cycle_reserve_edges(context, context->edge_count + 1);
    int edge = context->edge_count++;
    context->edges[edge] = (__btrc_cycle_edge){
        slot_storage, access, context->source, target,
        context->vertices[context->source].first_edge};
    context->vertices[context->source].first_edge = edge;
    size_t slot = __btrc_ptr_hash((const void*)slot_storage)
        & ((size_t)context->slot_cap - 1);
    while (context->slot_marks[slot] == context->slot_epoch)
        slot = (slot + 1) & ((size_t)context->slot_cap - 1);
    context->slot_marks[slot] = context->slot_epoch;
    context->slot_keys[slot] = slot_storage;
    context->slot_values[slot] = edge;
}
static void __btrc_cycle_snapshot(__btrc_cycle_context* context) {
    int seeds = __btrc_suspect_count;
    for (int i = 0; i < seeds; i++) {
        void* object = __btrc_suspects[i];
        if (!object) continue;
        __btrc_arc_validate(object);
        __btrc_arc_header* header = __btrc_arc_header_of(object);
        if (header->rc > header->edge_rc) continue;
        __btrc_arc_type fallback = {
            .visit = __btrc_visit_table[i],
            .destroy = __btrc_destroy_table[i],
            .hook = NULL, .guard = NULL, .raise = NULL};
        int root = __btrc_cycle_add_object(context, object, &fallback);
        if (context->vertices[root].state == 0) {
            context->vertices[root].state = 3;
            __btrc_cycle_push_queue(context, root);
        }
    }
    __btrc_suspect_count = 0;
    if (__btrc_suspect_keys) {
        size_t bytes = __btrc_cycle_capacity_bytes(
            __btrc_suspect_key_cap, sizeof(void*),
            "cycle suspect hash size overflow");
        memset(__btrc_suspect_keys, 0, bytes);
    }
    int head = 0;
    while (head < context->queue_count) {
        int scanned = context->queue[head++];
        __btrc_cycle_vertex* vertex = &context->vertices[scanned];
        if (vertex->state != 3) continue;
        __btrc_arc_validate(vertex->object);
        __btrc_arc_header* header = __btrc_arc_header_of(vertex->object);
        if (header->rc > header->edge_rc) {
            vertex->state = 2;
            vertex->live = 1;
            continue;
        }
        vertex->state = 1;
        vertex->live = 0;
        if (!vertex->visit) continue;
        context->source = scanned;
        vertex->visit(vertex->object, __btrc_cycle_snapshot_edge, context);
    }
}
static void __btrc_cycle_mark_live(__btrc_cycle_context* context) {
    __btrc_cycle_reserve_queue(context, context->vertex_count);
    int head = 0;
    int tail = 0;
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        __btrc_arc_validate(vertex->object);
        int rc = __btrc_arc_header_of(vertex->object)->rc;
        if (rc < vertex->internal)
            __btrc_cycle_fail("reference count below internal edge count");
        if (vertex->live || rc > vertex->internal) {
            vertex->live = 1;
            context->queue[tail++] = i;
        }
    }
    while (head < tail) {
        int source = context->queue[head++];
        for (int edge = context->vertices[source].first_edge;
                edge >= 0; edge = context->edges[edge].next) {
            int target = context->edges[edge].target;
            if (!context->vertices[target].live) {
                context->vertices[target].live = 1;
                context->queue[tail++] = target;
            }
        }
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        __btrc_arc_header* header =
            __btrc_arc_header_of(vertex->object);
        if (!vertex->live) {
            header->live_witness = NULL;
        } else if (header->rc == header->edge_rc
                && !header->live_witness) {
            /* Preserve a concrete owner; self is only the fallback proof. */
            header->live_witness = vertex->object;
        }
    }
}
static void __btrc_cycle_reclaim(__btrc_cycle_context* context) {
    for (int i = 0; i < context->edge_count; i++) {
        __btrc_cycle_edge* edge = &context->edges[i];
        if (context->vertices[edge->source].live) continue;
        void* target_object = context->vertices[edge->target].object;
        if (edge->access(edge->slot_storage,
                target_object, NULL, 1) != target_object)
            __btrc_cycle_fail("managed graph changed during cycle collection");
        __btrc_arc_unregister_incoming(
            context->vertices[edge->target].object,
            context->vertices[edge->source].object);
        __btrc_arc_header* target = __btrc_arc_header_of(
            context->vertices[edge->target].object);
        if (target->rc <= 0 || target->edge_rc <= 0)
            __btrc_cycle_fail("managed edge count underflow");
        target->rc--;
        target->edge_rc--;
        if (target->rc > 0)
            __btrc_arc_validate(context->vertices[edge->target].object);
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        if (vertex->live) continue;
        __btrc_arc_header* header = __btrc_arc_header_of(vertex->object);
        if (header->rc != 0 || header->edge_rc != 0)
            __btrc_cycle_fail("dead cycle retained an owned reference");
        if (header->incoming != NULL)
            __btrc_cycle_fail("dead cycle retained an incoming owner");
        __btrc_forget_suspect(vertex->object);
        __btrc_arc_enqueue_locked(vertex->object);
    }
}
static int __btrc_collect_cycles_once(void) {
    __btrc_arc_lock_raw();
    if (__btrc_arc_shutdown) {
        __btrc_arc_unlock_raw();
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    if (__btrc_suspect_count == 0) {
        __btrc_arc_unlock_raw();
        return 0;
    }
    if (__btrc_collecting) {
        __btrc_arc_topology_flush_pending = 1;
        __btrc_arc_unlock_raw();
        return 2;
    }
    if (atomic_load_explicit(
                &__btrc_arc_snapshot_pending, memory_order_acquire)
            || atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)) {
        __btrc_arc_topology_flush_pending = 1;
        __btrc_arc_unlock_raw();
        return 2;
    }
    if (__btrc_arc_topology_active > 0) {
        __btrc_arc_topology_flush_pending = 1;
        __btrc_arc_unlock_raw();
        return 2;
    }
    __btrc_collecting = 1;
    __btrc_arc_topology_flush_pending = 0;
    atomic_store_explicit(
        &__btrc_arc_snapshotting, 1, memory_order_release);
    __btrc_arc_unlock_raw();

    __btrc_cycle_context* context = &__btrc_cycle_scratch;
    __btrc_cycle_reset_context(context);
    __btrc_cycle_snapshot(context);
    __btrc_cycle_mark_live(context);

    __btrc_arc_lock_raw();
    __btrc_cycle_reclaim(context);
    __btrc_collecting = 0;
    atomic_store_explicit(
        &__btrc_arc_snapshotting, 0, memory_order_release);
    __btrc_arc_unlock_raw();
    return 1;
}
"""

__all__ = ["CYCLE_COLLECTOR_SUFFIX"]
