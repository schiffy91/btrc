"""Exact incoming-owner topology and reverse-root worklist."""

from .core import HelperDef

ARC_INCOMING_HELPERS = {
    "__btrc_arc_reverse_state": HelperDef(
        c_source=r"""/* Scratch state for exact reverse-root classification. */
static void** __btrc_reverse_queue = NULL;
static int __btrc_reverse_queue_cap = 0;
static void** __btrc_reverse_keys = NULL;
static unsigned int* __btrc_reverse_marks = NULL;
static int __btrc_reverse_key_cap = 0;
static int __btrc_reverse_count = 0;
static unsigned int __btrc_reverse_epoch = 0;""",
    ),
    "__btrc_arc_register_incoming": HelperDef(
        c_source=r"""static void __btrc_arc_register_incoming(
        void* object, void* owner) {
    if (!owner) {
        fprintf(stderr, "btrc: managed edge requires an owner\n");
        exit(1);
    }
    __btrc_arc_incoming* incoming = (__btrc_arc_incoming*)
        __btrc_safe_realloc(NULL, sizeof(__btrc_arc_incoming));
    incoming->owner = owner;
    incoming->next = __btrc_arc_header_of(object)->incoming;
    __btrc_arc_header_of(object)->incoming = incoming;
    if (owner != object) __btrc_arc_header_of(object)->live_witness = owner;
}""",
        depends_on=["__btrc_arc_header_of", "__btrc_safe_realloc"],
    ),
    "__btrc_arc_unregister_incoming": HelperDef(
        c_source=r"""static void __btrc_arc_unregister_incoming(
        void* object, void* owner) {
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (!owner) {
        header->live_witness = NULL;
        return;
    }
    __btrc_arc_incoming** link = &header->incoming;
    while (*link && (*link)->owner != owner) link = &(*link)->next;
    if (!*link) {
        fprintf(stderr, "btrc: missing managed incoming edge\n");
        exit(1);
    }
    __btrc_arc_incoming* removed = *link;
    *link = removed->next;
    free(removed);
    if (header->live_witness == object || header->live_witness == owner) {
        header->live_witness = NULL;
        for (__btrc_arc_incoming* edge = header->incoming;
                edge; edge = edge->next) {
            if (edge->owner != object) {
                header->live_witness = edge->owner;
                break;
            }
        }
    }
}""",
        depends_on=["__btrc_arc_header_of"],
    ),
    "__btrc_arc_incoming_teardown_pending": HelperDef(
        c_source=r"""static int __btrc_arc_incoming_teardown_pending(
        void* object) {
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (!header->incoming) return 0;
    for (__btrc_arc_incoming* edge = header->incoming;
            edge; edge = edge->next) {
        void* owner = edge->owner;
        if (!owner || owner == object) return 0;
        __btrc_arc_validate(owner);
        if (__btrc_arc_header_of(owner)->state != __BTRC_ARC_DESTROYING)
            return 0;
    }
    return 1;
}""",
        depends_on=["__btrc_arc_validate"],
    ),
    "__btrc_arc_reverse_proves_live": HelperDef(
        c_source=r"""static int __btrc_reverse_next_capacity(
        int capacity, const char* message) {
    if (capacity < 0 || capacity > INT_MAX / 2) {
        fprintf(stderr, "btrc: %s\n", message);
        exit(1);
    }
    return capacity ? capacity * 2 : 256;
}
static size_t __btrc_reverse_capacity_bytes(
        int capacity, size_t element_size, const char* message) {
    if (capacity < 0 || (element_size != 0
            && (size_t)capacity > SIZE_MAX / element_size)) {
        fprintf(stderr, "btrc: %s\n", message);
        exit(1);
    }
    return (size_t)capacity * element_size;
}
static void __btrc_reverse_reserve_queue(int needed) {
    if (needed < 0 || __btrc_reverse_queue_cap < 0) {
        fprintf(stderr, "btrc: reverse ARC queue overflow\n");
        exit(1);
    }
    if (needed <= __btrc_reverse_queue_cap) return;
    int cap = __btrc_reverse_queue_cap;
    while (cap < needed)
        cap = __btrc_reverse_next_capacity(
            cap, "reverse ARC queue overflow");
    size_t bytes = __btrc_reverse_capacity_bytes(
        cap, sizeof(void*), "reverse ARC queue size overflow");
    __btrc_reverse_queue = (void**)__btrc_safe_realloc(
        __btrc_reverse_queue, bytes);
    __btrc_reverse_queue_cap = cap;
}
static void __btrc_reverse_grow_keys(void) {
    int cap = __btrc_reverse_next_capacity(
        __btrc_reverse_key_cap, "reverse ARC hash overflow");
    size_t key_bytes = __btrc_reverse_capacity_bytes(
        cap, sizeof(void*), "reverse ARC hash size overflow");
    size_t mark_bytes = __btrc_reverse_capacity_bytes(
        cap, sizeof(unsigned int), "reverse ARC hash size overflow");
    void** keys = (void**)__btrc_safe_calloc(1, key_bytes);
    unsigned int* marks = (unsigned int*)__btrc_safe_calloc(1, mark_bytes);
    for (int i = 0; i < __btrc_reverse_count; i++) {
        void* object = __btrc_reverse_queue[i];
        size_t slot = __btrc_ptr_hash(object) & ((size_t)cap - 1);
        while (marks[slot] == __btrc_reverse_epoch)
            slot = (slot + 1) & ((size_t)cap - 1);
        marks[slot] = __btrc_reverse_epoch;
        keys[slot] = object;
    }
    free(__btrc_reverse_keys);
    free(__btrc_reverse_marks);
    __btrc_reverse_keys = keys;
    __btrc_reverse_marks = marks;
    __btrc_reverse_key_cap = cap;
}
static int __btrc_reverse_add(void* object) {
    if (!object) return 0;
    if (__btrc_reverse_count < 0 || __btrc_reverse_count == INT_MAX) {
        fprintf(stderr, "btrc: reverse ARC count overflow\n");
        exit(1);
    }
    if (__btrc_reverse_key_cap == 0
            || __btrc_reverse_count >= __btrc_reverse_key_cap / 2)
        __btrc_reverse_grow_keys();
    size_t slot = __btrc_ptr_hash(object)
        & ((size_t)__btrc_reverse_key_cap - 1);
    while (__btrc_reverse_marks[slot] == __btrc_reverse_epoch) {
        if (__btrc_reverse_keys[slot] == object) return 0;
        slot = (slot + 1) & ((size_t)__btrc_reverse_key_cap - 1);
    }
    __btrc_reverse_reserve_queue(__btrc_reverse_count + 1);
    __btrc_reverse_marks[slot] = __btrc_reverse_epoch;
    __btrc_reverse_keys[slot] = object;
    __btrc_reverse_queue[__btrc_reverse_count++] = object;
    return 1;
}
static int __btrc_arc_reverse_proves_live(void* object) {
    __btrc_reverse_count = 0;
    __btrc_reverse_epoch++;
    if (__btrc_reverse_epoch == 0) {
        if (__btrc_reverse_marks) {
            size_t bytes = __btrc_reverse_capacity_bytes(
                __btrc_reverse_key_cap, sizeof(unsigned int),
                "reverse ARC hash size overflow");
            memset(__btrc_reverse_marks, 0, bytes);
        }
        __btrc_reverse_epoch = 1;
    }
    __btrc_reverse_add(object);
    for (int head = 0; head < __btrc_reverse_count; head++) {
        void* current = __btrc_reverse_queue[head];
        __btrc_arc_validate(current);
        __btrc_arc_header* header = __btrc_arc_header_of(current);
        if (header->rc > header->edge_rc) return 1;
        for (__btrc_arc_incoming* edge = header->incoming;
                edge; edge = edge->next)
            __btrc_reverse_add(edge->owner);
    }
    return 0;
}""",
        depends_on=[
            "__btrc_arc_reverse_state",
            "__btrc_arc_validate",
            "__btrc_ptr_hash",
            "__btrc_safe_calloc",
            "__btrc_safe_realloc",
        ],
    ),
}

__all__ = ["ARC_INCOMING_HELPERS"]
