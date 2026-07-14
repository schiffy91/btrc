"""Allocation and lookup half of the cycle-collector C runtime."""

CYCLE_COLLECTOR_STATE = r"""
/* ARC cycle collector: typed graph snapshot, O(vertices + edges). */
typedef struct {
    void* object;
    __btrc_visit_fn visit;
    __btrc_destroy_fn destroy;
    int internal;
    int first_edge;
    unsigned char live;
    unsigned char state;
    unsigned char root;
} __btrc_cycle_vertex;
typedef struct {
    volatile void* slot_storage;
    __btrc_arc_slot_access_fn access;
    int source;
    int target;
    int next;
} __btrc_cycle_edge;
typedef struct {
    __btrc_cycle_vertex* vertices;
    __btrc_cycle_edge* edges;
    int* queue;
    int vertex_count;
    int vertex_cap;
    int edge_count;
    int edge_cap;
    int queue_cap;
    int queue_count;
    int source;
    void** object_keys;
    int* object_values;
    unsigned int* object_marks;
    int object_cap;
    unsigned int object_epoch;
    volatile void** slot_keys;
    int* slot_values;
    unsigned int* slot_marks;
    int slot_cap;
    unsigned int slot_epoch;
} __btrc_cycle_context;
static __btrc_cycle_context __btrc_cycle_scratch;
static int __btrc_collecting = 0;
"""

CYCLE_COLLECTOR_PRIMITIVES = r"""
static void __btrc_cycle_fail(const char* message) {
    fprintf(stderr, "btrc: %s\n", message);
    exit(1);
}
static void __btrc_cycle_next_epoch(
        unsigned int* epoch, unsigned int* marks, int cap) {
    (*epoch)++;
    if (*epoch == 0) {
        if (marks) memset(marks, 0, sizeof(unsigned int) * (size_t)cap);
        *epoch = 1;
    }
}
static void __btrc_cycle_reserve_vertices(
        __btrc_cycle_context* context, int needed) {
    if (needed <= context->vertex_cap) return;
    int cap = context->vertex_cap ? context->vertex_cap : 256;
    while (cap < needed) {
        if (cap > INT_MAX / 2) __btrc_cycle_fail("cycle vertex overflow");
        cap *= 2;
    }
    context->vertices = (__btrc_cycle_vertex*)__btrc_safe_realloc(
        context->vertices, sizeof(__btrc_cycle_vertex) * (size_t)cap);
    context->vertex_cap = cap;
}
static void __btrc_cycle_reserve_edges(
        __btrc_cycle_context* context, int needed) {
    if (needed <= context->edge_cap) return;
    int cap = context->edge_cap ? context->edge_cap : 256;
    while (cap < needed) {
        if (cap > INT_MAX / 2) __btrc_cycle_fail("cycle edge overflow");
        cap *= 2;
    }
    context->edges = (__btrc_cycle_edge*)__btrc_safe_realloc(
        context->edges, sizeof(__btrc_cycle_edge) * (size_t)cap);
    context->edge_cap = cap;
}
static void __btrc_cycle_reserve_queue(
        __btrc_cycle_context* context, int needed) {
    if (needed <= context->queue_cap) return;
    int cap = context->queue_cap ? context->queue_cap : 256;
    while (cap < needed) {
        if (cap > INT_MAX / 2) __btrc_cycle_fail("cycle queue overflow");
        cap *= 2;
    }
    context->queue = (int*)__btrc_safe_realloc(
        context->queue, sizeof(int) * (size_t)cap);
    context->queue_cap = cap;
}
static void __btrc_cycle_grow_objects(__btrc_cycle_context* context) {
    if (context->object_cap > INT_MAX / 2)
        __btrc_cycle_fail("cycle object hash overflow");
    int cap = context->object_cap ? context->object_cap * 2 : 256;
    void** keys = (void**)calloc((size_t)cap, sizeof(void*));
    int* values = (int*)malloc(sizeof(int) * (size_t)cap);
    unsigned int* marks = (unsigned int*)calloc(
        (size_t)cap, sizeof(unsigned int));
    if (!keys || !values || !marks)
        __btrc_cycle_fail("cycle object hash allocation failed");
    for (int i = 0; i < context->vertex_count; i++) {
        void* object = context->vertices[i].object;
        size_t slot = __btrc_ptr_hash(object) & ((size_t)cap - 1);
        while (marks[slot] == context->object_epoch)
            slot = (slot + 1) & ((size_t)cap - 1);
        marks[slot] = context->object_epoch;
        keys[slot] = object;
        values[slot] = i;
    }
    free(context->object_keys);
    free(context->object_values);
    free(context->object_marks);
    context->object_keys = keys;
    context->object_values = values;
    context->object_marks = marks;
    context->object_cap = cap;
}
static int __btrc_cycle_find_object(
        __btrc_cycle_context* context, void* object) {
    if (context->object_cap == 0) return -1;
    size_t slot = __btrc_ptr_hash(object)
        & ((size_t)context->object_cap - 1);
    while (context->object_marks[slot] == context->object_epoch) {
        if (context->object_keys[slot] == object)
            return context->object_values[slot];
        slot = (slot + 1) & ((size_t)context->object_cap - 1);
    }
    return -1;
}
static int __btrc_cycle_add_object(__btrc_cycle_context* context,
        void* object, const __btrc_arc_type* fallback) {
    if (!object) __btrc_cycle_fail("null managed cycle edge");
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy)
        __btrc_cycle_fail("untyped managed cycle edge");
    int found = __btrc_cycle_find_object(context, object);
    if (found >= 0) {
        __btrc_cycle_vertex* vertex = &context->vertices[found];
        if (vertex->visit != type->visit || vertex->destroy != type->destroy)
            __btrc_cycle_fail("conflicting runtime types for cycle object");
        return found;
    }
    if (context->object_cap == 0
            || context->vertex_count >= context->object_cap / 2)
        __btrc_cycle_grow_objects(context);
    __btrc_cycle_reserve_vertices(context, context->vertex_count + 1);
    int index = context->vertex_count++;
    context->vertices[index] = (__btrc_cycle_vertex){
        object, type->visit, type->destroy, 0, -1, 0, 0, 0};
    size_t slot = __btrc_ptr_hash(object)
        & ((size_t)context->object_cap - 1);
    while (context->object_marks[slot] == context->object_epoch)
        slot = (slot + 1) & ((size_t)context->object_cap - 1);
    context->object_marks[slot] = context->object_epoch;
    context->object_keys[slot] = object;
    context->object_values[slot] = index;
    return index;
}
static void __btrc_cycle_grow_slots(__btrc_cycle_context* context) {
    if (context->slot_cap > INT_MAX / 2)
        __btrc_cycle_fail("cycle slot hash overflow");
    int cap = context->slot_cap ? context->slot_cap * 2 : 256;
    volatile void** keys = (volatile void**)calloc(
        (size_t)cap, sizeof(volatile void*));
    int* values = (int*)malloc(sizeof(int) * (size_t)cap);
    unsigned int* marks = (unsigned int*)calloc(
        (size_t)cap, sizeof(unsigned int));
    if (!keys || !values || !marks)
        __btrc_cycle_fail("cycle slot hash allocation failed");
    for (int i = 0; i < context->edge_count; i++) {
        volatile void* storage = context->edges[i].slot_storage;
        size_t slot = __btrc_ptr_hash((const void*)storage)
            & ((size_t)cap - 1);
        while (marks[slot] == context->slot_epoch)
            slot = (slot + 1) & ((size_t)cap - 1);
        marks[slot] = context->slot_epoch;
        keys[slot] = storage;
        values[slot] = i;
    }
    free(context->slot_keys);
    free(context->slot_values);
    free(context->slot_marks);
    context->slot_keys = keys;
    context->slot_values = values;
    context->slot_marks = marks;
    context->slot_cap = cap;
}
static int __btrc_cycle_find_slot(
        __btrc_cycle_context* context, volatile void* storage) {
    if (context->slot_cap == 0) return -1;
    size_t slot = __btrc_ptr_hash((const void*)storage)
        & ((size_t)context->slot_cap - 1);
    while (context->slot_marks[slot] == context->slot_epoch) {
        if (context->slot_keys[slot] == storage)
            return context->slot_values[slot];
        slot = (slot + 1) & ((size_t)context->slot_cap - 1);
    }
    return -1;
}
static void __btrc_cycle_reset_context(__btrc_cycle_context* context) {
    context->vertex_count = 0;
    context->edge_count = 0;
    context->source = -1;
    context->queue_count = 0;
    __btrc_cycle_next_epoch(&context->object_epoch,
        context->object_marks, context->object_cap);
    __btrc_cycle_next_epoch(&context->slot_epoch,
        context->slot_marks, context->slot_cap);
}
"""

CYCLE_COLLECTOR_PREFIX = CYCLE_COLLECTOR_STATE + CYCLE_COLLECTOR_PRIMITIVES

__all__ = [
    "CYCLE_COLLECTOR_PREFIX",
    "CYCLE_COLLECTOR_PRIMITIVES",
    "CYCLE_COLLECTOR_STATE",
]
