"""Cycle-candidate buffers and checked hash-table growth."""

from .core import HelperDef

ARC_SUSPECT_HELPERS = {
    "__btrc_suspect_state": HelperDef(
        c_source=r"""/* ARC cycle detection: suspect buffer */
static void** __btrc_suspects = NULL;
static int __btrc_suspect_count = 0;
static __btrc_visit_fn* __btrc_visit_table = NULL;
static __btrc_destroy_fn* __btrc_destroy_table = NULL;
static void** __btrc_suspect_keys = NULL;
static int __btrc_suspect_key_cap = 0;""",
        depends_on=["__btrc_arc_callback_types"],
    ),
    "__btrc_suspect_capacity": HelperDef(
        c_source="static int __btrc_suspect_cap = 0;",
    ),
    "__btrc_ptr_hash": HelperDef(
        c_source=r"""static size_t __btrc_ptr_hash(const void* ptr) {
    uintptr_t value = (uintptr_t)ptr;
    value ^= value >> 17;
    value ^= value >> 9;
    return (size_t)value;
}""",
    ),
    "__btrc_suspect_locked": HelperDef(
        c_source=r"""static int __btrc_suspect_next_capacity(
        int capacity, const char* message) {
    if (capacity < 0 || capacity > INT_MAX / 2) {
        fprintf(stderr, "btrc: %s\n", message);
        exit(1);
    }
    return capacity ? capacity * 2 : 256;
}
static size_t __btrc_suspect_capacity_bytes(
        int capacity, size_t element_size, const char* message) {
    if (capacity < 0 || (element_size != 0
            && (size_t)capacity > SIZE_MAX / element_size)) {
        fprintf(stderr, "btrc: %s\n", message);
        exit(1);
    }
    return (size_t)capacity * element_size;
}
static void __btrc_grow_suspect_keys_locked(void) {
    int cap = __btrc_suspect_next_capacity(
        __btrc_suspect_key_cap, "cycle suspect hash overflow");
    size_t bytes = __btrc_suspect_capacity_bytes(
        cap, sizeof(void*), "cycle suspect hash size overflow");
    void** keys = (void**)__btrc_safe_calloc(1, bytes);
    for (int i = 0; i < __btrc_suspect_count; i++) {
        size_t index = __btrc_ptr_hash(__btrc_suspects[i]) & ((size_t)cap - 1);
        while (keys[index]) index = (index + 1) & ((size_t)cap - 1);
        keys[index] = __btrc_suspects[i];
    }
    free(__btrc_suspect_keys);
    __btrc_suspect_keys = keys;
    __btrc_suspect_key_cap = cap;
}
static inline void __btrc_suspect_locked(void* obj, __btrc_visit_fn visit,
                           __btrc_destroy_fn destroy) {
    if (!obj) return;
    __btrc_arc_validate(obj);
    __btrc_arc_header* header = __btrc_arc_header_of(obj);
    if (header->rc > header->edge_rc) return;
    __btrc_arc_type fallback = {
        .visit = visit, .destroy = destroy,
        .hook = NULL, .guard = NULL, .raise = NULL};
    const __btrc_arc_type* type = __btrc_arc_type_of(obj, &fallback);
    if (!type || !type->visit || !type->destroy) return;
    if (__btrc_suspect_count < 0 || __btrc_suspect_count == INT_MAX
            || __btrc_suspect_cap < 0
            || __btrc_suspect_count > __btrc_suspect_cap) {
        fprintf(stderr, "btrc: cycle suspect overflow\n");
        exit(1);
    }
    if (__btrc_suspect_key_cap == 0
            || __btrc_suspect_count >= __btrc_suspect_key_cap / 2)
        __btrc_grow_suspect_keys_locked();
    size_t key = __btrc_ptr_hash(obj)
        & ((size_t)__btrc_suspect_key_cap - 1);
    while (__btrc_suspect_keys[key]) {
        if (__btrc_suspect_keys[key] == obj) return;
        key = (key + 1) & ((size_t)__btrc_suspect_key_cap - 1);
    }
    if (__btrc_suspect_count >= __btrc_suspect_cap) {
        int new_cap = __btrc_suspect_next_capacity(
            __btrc_suspect_cap, "cycle suspect overflow");
        size_t object_bytes = __btrc_suspect_capacity_bytes(
            new_cap, sizeof(void*), "cycle suspect size overflow");
        size_t visit_bytes = __btrc_suspect_capacity_bytes(
            new_cap, sizeof(__btrc_visit_fn),
            "cycle suspect size overflow");
        size_t destroy_bytes = __btrc_suspect_capacity_bytes(
            new_cap, sizeof(__btrc_destroy_fn),
            "cycle suspect size overflow");
        __btrc_suspects = (void**)__btrc_safe_realloc(
            __btrc_suspects, object_bytes);
        __btrc_visit_table = (__btrc_visit_fn*)__btrc_safe_realloc(
            __btrc_visit_table, visit_bytes);
        __btrc_destroy_table = (__btrc_destroy_fn*)__btrc_safe_realloc(
            __btrc_destroy_table, destroy_bytes);
        __btrc_suspect_cap = new_cap;
    }
    __btrc_suspects[__btrc_suspect_count] = obj;
    __btrc_visit_table[__btrc_suspect_count] = type->visit;
    __btrc_destroy_table[__btrc_suspect_count] = type->destroy;
    __btrc_suspect_keys[key] = obj;
    __btrc_suspect_count++;
}""",
        depends_on=[
            "__btrc_suspect_state",
            "__btrc_suspect_capacity",
            "__btrc_ptr_hash",
            "__btrc_safe_calloc",
            "__btrc_safe_realloc",
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
        ],
    ),
    "__btrc_suspect": HelperDef(
        c_source=r"""static inline void __btrc_suspect(
        void* obj, __btrc_visit_fn visit, __btrc_destroy_fn destroy) {
    __btrc_arc_lock_mutation();
    __btrc_suspect_locked(obj, visit, destroy);
    __btrc_arc_unlock_mutation();
}""",
        depends_on=["__btrc_suspect_locked", "__btrc_arc_mutation_lock"],
    ),
}

__all__ = ["ARC_SUSPECT_HELPERS"]
