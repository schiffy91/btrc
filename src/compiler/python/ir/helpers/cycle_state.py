"""ARC header, destroyed-object tracking, and cycle candidate state."""

from .core import HelperDef

ARC_STATE_HELPERS = {
    "__btrc_arc_callback_types": HelperDef(
        c_source=r"""/* Type-erased ARC metadata shared by ownership paths. */
typedef int __btrc_arc_count;
typedef struct __btrc_arc_type __btrc_arc_type;
typedef struct __btrc_arc_incoming __btrc_arc_incoming;
typedef struct __btrc_arc_header {
    __btrc_arc_count rc;
    __btrc_arc_count edge_rc;
    /* One current incoming-edge owner, or self as a full-snapshot sentinel. */
    void* live_witness;
    const __btrc_arc_type* type;
    __btrc_arc_incoming* incoming;
} __btrc_arc_header;
struct __btrc_arc_incoming {
    void* owner;
    __btrc_arc_incoming* next;
};
typedef void (*__btrc_destroy_fn)(void*);
typedef void (*__btrc_field_visit_fn)(
    void**, const __btrc_arc_type*, void*);
typedef void (*__btrc_visit_fn)(
    void*, __btrc_field_visit_fn, void*);
struct __btrc_arc_type {
    __btrc_visit_fn visit;
    __btrc_destroy_fn destroy;
};""",
    ),
    "__btrc_arc_header_of": HelperDef(
        c_source=r"""static inline __btrc_arc_header* __btrc_arc_header_of(void* object) {
    return (__btrc_arc_header*)object;
}""",
        depends_on=["__btrc_arc_callback_types"],
    ),
    "__btrc_arc_type_of": HelperDef(
        c_source=r"""static inline const __btrc_arc_type* __btrc_arc_type_of(
        void* object, const __btrc_arc_type* fallback) {
    if (object && __btrc_arc_header_of(object)->type)
        return __btrc_arc_header_of(object)->type;
    return fallback;
}""",
        depends_on=["__btrc_arc_header_of"],
    ),
    "__btrc_arc_validate": HelperDef(
        c_source=r"""static inline void __btrc_arc_validate(void* object) {
    if (!object) return;
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->rc < 0 || header->edge_rc < 0
            || header->edge_rc > header->rc || !header->type
            || !header->type->destroy) {
        fprintf(stderr, "btrc: invalid ARC header\n");
        exit(1);
    }
}""",
        depends_on=["__btrc_arc_header_of"],
    ),
    "__btrc_destroyed_tracking": HelperDef(
        c_source=(
            "/* ARC cascade-destroy tracking: avoid reading freed memory */\n"
            "static _Atomic int __btrc_tracking = 0;\n"
            "static void** __btrc_destroyed = NULL;\n"
            "static int __btrc_destroyed_count = 0;"
        ),
        required_headers=["stdatomic.h"],
    ),
    "__btrc_destroyed_tracking_scope": HelperDef(
        c_source=r"""static void __btrc_destroyed_tracking_begin(void) {
    __btrc_arc_lock_mutation();
    int active = atomic_load_explicit(
        &__btrc_tracking, memory_order_relaxed);
    if (active == 0) __btrc_destroyed_count = 0;
    if (active == INT_MAX) {
        fprintf(stderr, "btrc: destroyed tracking depth overflow\n");
        exit(1);
    }
    atomic_store_explicit(
        &__btrc_tracking, active + 1, memory_order_release);
    __btrc_arc_unlock_mutation();
}
static void __btrc_destroyed_tracking_end(void) {
    __btrc_arc_lock_mutation();
    int active = atomic_load_explicit(
        &__btrc_tracking, memory_order_relaxed);
    if (active <= 0) {
        fprintf(stderr, "btrc: unbalanced destroyed tracking scope\n");
        exit(1);
    }
    active--;
    atomic_store_explicit(
        &__btrc_tracking, active, memory_order_release);
    if (active == 0) __btrc_destroyed_count = 0;
    __btrc_arc_unlock_mutation();
}""",
        depends_on=[
            "__btrc_destroyed_tracking",
            "__btrc_arc_mutation_lock",
        ],
    ),
    "__btrc_is_destroyed": HelperDef(
        c_source=r"""static int __btrc_is_destroyed(void* ptr) {
    if (!ptr) return 0;
    __btrc_arc_lock_mutation();
    for (int i = 0; i < __btrc_destroyed_count; i++) {
        if (__btrc_destroyed[i] != ptr) continue;
        __btrc_arc_unlock_mutation();
        return 1;
    }
    __btrc_arc_unlock_mutation();
    return 0;
}""",
        depends_on=["__btrc_destroyed_tracking", "__btrc_arc_mutation_lock"],
    ),
    "__btrc_destroyed_capacity": HelperDef(
        c_source="static int __btrc_destroyed_cap = 0;",
    ),
    "__btrc_mark_destroyed": HelperDef(
        c_source=r"""static void __btrc_mark_destroyed(void* ptr) {
    if (!ptr) return;
    __btrc_arc_lock_mutation();
    if (!atomic_load_explicit(
            &__btrc_tracking, memory_order_acquire)) {
        __btrc_arc_unlock_mutation();
        return;
    }
    for (int i = 0; i < __btrc_destroyed_count; i++) {
        if (__btrc_destroyed[i] != ptr) continue;
        __btrc_arc_unlock_mutation();
        return;
    }
    if (__btrc_destroyed_count >= __btrc_destroyed_cap) {
        if (__btrc_destroyed_cap > INT_MAX / 2) { fprintf(stderr, "btrc: destroyed tracking overflow\n"); exit(1); }
        int new_cap = __btrc_destroyed_cap ? __btrc_destroyed_cap * 2 : 256;
        if ((size_t)new_cap > SIZE_MAX / sizeof(void*)) { fprintf(stderr, "btrc: destroyed tracking size overflow\n"); exit(1); }
        __btrc_destroyed = (void**)__btrc_safe_realloc(
            __btrc_destroyed, sizeof(void*) * (size_t)new_cap);
        __btrc_destroyed_cap = new_cap;
    }
    __btrc_destroyed[__btrc_destroyed_count++] = ptr;
    __btrc_arc_unlock_mutation();
}""",
        depends_on=[
            "__btrc_destroyed_tracking",
            "__btrc_destroyed_capacity",
            "__btrc_safe_realloc",
            "__btrc_arc_mutation_lock",
        ],
    ),
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
        c_source=r"""static void __btrc_grow_suspect_keys_locked(void) {
    if (__btrc_suspect_key_cap > INT_MAX / 2) { fprintf(stderr, "btrc: cycle suspect hash overflow\n"); exit(1); }
    int cap = __btrc_suspect_key_cap ? __btrc_suspect_key_cap * 2 : 256;
    void** keys = (void**)calloc((size_t)cap, sizeof(void*));
    if (!keys) { fprintf(stderr, "btrc: cycle suspect hash allocation failed\n"); exit(1); }
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
    __btrc_arc_type fallback = {visit, destroy};
    const __btrc_arc_type* type = __btrc_arc_type_of(obj, &fallback);
    if (!type || !type->visit || !type->destroy) return;
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
        if (__btrc_suspect_cap > INT_MAX / 2) { fprintf(stderr, "btrc: cycle suspect overflow\n"); exit(1); }
        int new_cap = __btrc_suspect_cap ? __btrc_suspect_cap * 2 : 256;
        if ((size_t)new_cap > SIZE_MAX / sizeof(void*)
                || (size_t)new_cap > SIZE_MAX / sizeof(__btrc_visit_fn)
                || (size_t)new_cap > SIZE_MAX / sizeof(__btrc_destroy_fn)) { fprintf(stderr, "btrc: cycle suspect size overflow\n"); exit(1); }
        __btrc_suspects = (void**)__btrc_safe_realloc(
            __btrc_suspects, sizeof(void*) * (size_t)new_cap);
        __btrc_visit_table = (__btrc_visit_fn*)__btrc_safe_realloc(
            __btrc_visit_table, sizeof(__btrc_visit_fn) * (size_t)new_cap);
        __btrc_destroy_table = (__btrc_destroy_fn*)__btrc_safe_realloc(
            __btrc_destroy_table, sizeof(__btrc_destroy_fn) * (size_t)new_cap);
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
            "__btrc_safe_realloc",
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
        ],
    ),
    "__btrc_suspect": HelperDef(
        c_source=r"""static void __btrc_suspect(
        void* obj, __btrc_visit_fn visit, __btrc_destroy_fn destroy) {
    __btrc_arc_lock_mutation();
    __btrc_suspect_locked(obj, visit, destroy);
    __btrc_arc_unlock_mutation();
}""",
        depends_on=["__btrc_suspect_locked", "__btrc_arc_mutation_lock"],
    ),
}

__all__ = ["ARC_STATE_HELPERS"]
