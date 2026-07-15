"""Transactional teardown for a failed, nonescaping construction graph."""

from .core import HelperDef

ARC_ABANDON_HELPERS = {
    "__btrc_arc_abandon_graph": HelperDef(
        c_source=r"""static void __btrc_abandon_snapshot_edge(
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
        __btrc_cycle_fail("partial-construction edge overflow");
    context->vertices[target].internal++;
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
    if (context->vertices[target].state == 0) {
        context->vertices[target].state = 3;
        __btrc_cycle_push_queue(context, target);
    }
}

static void __btrc_abandon_snapshot(
        __btrc_cycle_context* context,
        void** roots, int root_count) {
    if (!roots || root_count <= 0)
        __btrc_cycle_fail("invalid construction roots");
    __btrc_cycle_reserve_queue(context, root_count);
    for (int i = 0; i < root_count; i++) {
        void* root = roots[i];
        int root_index = __btrc_cycle_add_object(
            context, root, __btrc_arc_header_of(root)->type);
        __btrc_cycle_vertex* vertex = &context->vertices[root_index];
        if (vertex->root)
            __btrc_cycle_fail("duplicate construction root");
        vertex->root = 1;
        if (vertex->state == 0) {
            vertex->state = 3;
            __btrc_cycle_push_queue(context, root_index);
        }
    }
    int head = 0;
    while (head < context->queue_count) {
        int current = context->queue[head++];
        __btrc_cycle_vertex* vertex = &context->vertices[current];
        vertex->state = 1;
        if (!vertex->visit) continue;
        context->source = current;
        vertex->visit(
            vertex->object, __btrc_abandon_snapshot_edge, context);
    }
}

static void __btrc_abandon_mark_live(
        __btrc_cycle_context* context) {
    __btrc_cycle_reserve_queue(context, context->vertex_count);
    int head = 0;
    int tail = 0;
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        __btrc_arc_header* header =
            __btrc_arc_header_of(vertex->object);
        int incoming = 0;
        for (__btrc_arc_incoming* edge = header->incoming;
                edge; edge = edge->next) {
            if (incoming == INT_MAX)
                __btrc_cycle_fail("partial-construction incoming overflow");
            incoming++;
        }
        int root_hold = vertex->root ? 1 : 0;
        if (root_hold && vertex->internal == INT_MAX)
            __btrc_cycle_fail("partial-construction root count overflow");
        int owned = vertex->internal + root_hold;
        if (header->state != __BTRC_ARC_LIVE
                || incoming != header->edge_rc
                || header->rc < owned
                || header->edge_rc < vertex->internal)
            __btrc_cycle_fail("invalid escaping partial construction");
        if (vertex->root && header->edge_rc != vertex->internal)
            __btrc_cycle_fail("invalid escaping partial construction");
        if (header->rc > owned) {
            vertex->live = 1;
            context->queue[tail++] = i;
        }
    }
    while (head < tail) {
        int source = context->queue[head++];
        for (int edge = context->vertices[source].first_edge;
                edge >= 0; edge = context->edges[edge].next) {
            int target = context->edges[edge].target;
            if (context->vertices[target].live) continue;
            context->vertices[target].live = 1;
            context->queue[tail++] = target;
        }
    }
    for (int i = 0; i < context->vertex_count; i++) {
        if (context->vertices[i].root
                && context->vertices[i].live)
            __btrc_cycle_fail("invalid escaping partial construction");
    }
}

static void __btrc_abandon_reclaim(__btrc_cycle_context* context) {
    for (int i = 0; i < context->edge_count; i++) {
        __btrc_cycle_edge* edge = &context->edges[i];
        if (context->vertices[edge->source].live) continue;
        void* source = context->vertices[edge->source].object;
        void* target = context->vertices[edge->target].object;
        if (edge->access(edge->slot_storage,
                target, NULL, 1) != target)
            __btrc_cycle_fail("managed graph changed during construction abandon");
        __btrc_arc_unregister_incoming(target, source);
        __btrc_arc_header* header = __btrc_arc_header_of(target);
        if (header->rc <= 0 || header->edge_rc <= 0)
            __btrc_cycle_fail("partial-construction edge underflow");
        header->rc--;
        header->edge_rc--;
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        if (!vertex->root) continue;
        __btrc_arc_header* root =
            __btrc_arc_header_of(vertex->object);
        if (root->rc <= 0)
            __btrc_cycle_fail("partial-construction root underflow");
        root->rc--;
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        __btrc_arc_header* header =
            __btrc_arc_header_of(vertex->object);
        if (vertex->live) {
            __btrc_arc_validate(vertex->object);
            continue;
        }
        if (header->rc != 0 || header->edge_rc != 0
                || header->incoming != NULL)
            __btrc_cycle_fail("partial construction retained a reference");
        __btrc_forget_suspect(vertex->object);
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        if (vertex->live) continue;
        if (vertex->root)
            __btrc_arc_header_of(vertex->object)->suppress_hook = 1;
        __btrc_arc_enqueue_locked(vertex->object);
    }
}

static void __btrc_arc_abandon_many(
        void** roots, int root_count, int free_roots) {
    if (!roots || root_count <= 0) return;
    __btrc_arc_exclusive_snapshot_begin();
    __btrc_cycle_context* context = &__btrc_cycle_scratch;
    __btrc_cycle_reset_context(context);
    __btrc_abandon_snapshot(context, roots, root_count);
    __btrc_abandon_mark_live(context);
    __btrc_arc_lock_raw();
    __btrc_abandon_reclaim(context);
    __btrc_arc_unlock_raw();
    __btrc_arc_exclusive_snapshot_end();
    if (free_roots) free(roots);
    __btrc_arc_drain_deferred(0);
}

static void __btrc_arc_abandon_now(void* object) {
    if (!object) return;
    void* roots[1] = {object};
    __btrc_arc_abandon_many(roots, 1, 0);
}""",
        depends_on=[
            "__btrc_arc_graph_primitives",
            "__btrc_arc_unregister_incoming",
            "__btrc_forget_suspect",
            "__btrc_arc_exclusive_snapshot",
            "__btrc_arc_deferred_state",
            "__btrc_arc_drain",
        ],
        required_headers=["stdlib.h"],
    ),
}

__all__ = ["ARC_ABANDON_HELPERS"]
