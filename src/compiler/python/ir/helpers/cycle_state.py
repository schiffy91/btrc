"""ARC header, destroyed-object tracking, and cycle candidate state."""

from .core import HelperDef
from .cycle_suspects import ARC_SUSPECT_HELPERS

ARC_STATE_HELPERS = {
    "__btrc_arc_callback_types": HelperDef(
        c_source=r"""/* Type-erased ARC metadata shared by ownership paths. */
typedef int __btrc_arc_count;
typedef struct __btrc_arc_type __btrc_arc_type;
typedef struct __btrc_arc_incoming __btrc_arc_incoming;
typedef enum {
    __BTRC_ARC_LIVE = 1,
    __BTRC_ARC_QUEUED = 2,
    __BTRC_ARC_DESTROYING = 3
} __btrc_arc_state;
typedef struct __btrc_arc_header {
    __btrc_arc_count rc;
    __btrc_arc_count edge_rc;
    /* One current incoming-edge owner, or self as a full-snapshot sentinel. */
    void* live_witness;
    const __btrc_arc_type* type;
    __btrc_arc_incoming* incoming;
    void* deferred_next;
    unsigned char suppress_hook;
    __btrc_arc_state state;
} __btrc_arc_header;
struct __btrc_arc_incoming {
    void* owner;
    __btrc_arc_incoming* next;
};
typedef void (*__btrc_destroy_fn)(void*);
typedef void* (*__btrc_arc_slot_access_fn)(
    volatile void*, void*, void*, int);
typedef void (*__btrc_field_visit_fn)(
    volatile void*, __btrc_arc_slot_access_fn,
    const __btrc_arc_type*, void*);
typedef void (*__btrc_visit_fn)(
    void*, __btrc_field_visit_fn, void*);
typedef void (*__btrc_hook_fn)(void*);
typedef int (*__btrc_hook_guard_fn)(
    __btrc_hook_fn, void*, char*, size_t);
typedef void (*__btrc_raise_fn)(const char*);
struct __btrc_arc_type {
    __btrc_visit_fn visit;
    __btrc_destroy_fn destroy;
    __btrc_hook_fn hook;
    __btrc_hook_guard_fn guard;
    __btrc_raise_fn raise;
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
    int live = header->state == __BTRC_ARC_LIVE
        && header->rc > 0 && header->edge_rc >= 0
        && header->edge_rc <= header->rc
        && header->deferred_next == NULL && !header->suppress_hook;
    int queued = header->state == __BTRC_ARC_QUEUED
        && header->rc == 0 && header->edge_rc == 0
        && header->live_witness == NULL && header->incoming == NULL;
    int destroying = header->state == __BTRC_ARC_DESTROYING
        && header->rc == 0 && header->edge_rc == 0
        && header->live_witness == NULL && header->incoming == NULL
        && header->deferred_next == NULL && !header->suppress_hook;
    if ((!live && !queued && !destroying) || !header->type
            || !header->type->destroy
            || (header->type->hook
                && (!header->type->guard || !header->type->raise))) {
        fprintf(stderr, "btrc: invalid ARC header\n");
        exit(1);
    }
}""",
        depends_on=["__btrc_arc_header_of"],
    ),
    "__btrc_destroyed_tracking": HelperDef(
        c_source=(
            "/* ARC cascade-destroy tracking: avoid reading freed memory */\n"
            "static _Thread_local int __btrc_tracking = 0;\n"
            "static _Thread_local void** __btrc_destroyed = NULL;\n"
            "static _Thread_local int __btrc_destroyed_count = 0;"
        ),
    ),
    "__btrc_destroyed_tracking_scope": HelperDef(
        c_source=r"""static void __btrc_destroyed_tracking_begin(void) {
    __btrc_arc_lock_mutation();
    int active = __btrc_tracking;
    if (active == 0) {
        __btrc_destroyed_count = 0;
        if (__btrc_arc_active_unwinds == INT_MAX) {
            fprintf(stderr, "btrc: active unwind count overflow\n");
            exit(1);
        }
        __btrc_arc_active_unwinds++;
    }
    if (active == INT_MAX) {
        fprintf(stderr, "btrc: destroyed tracking depth overflow\n");
        exit(1);
    }
    __btrc_tracking = active + 1;
    __btrc_arc_unlock_mutation();
}
static void __btrc_destroyed_tracking_end(void) {
    __btrc_arc_lock_mutation();
    int active = __btrc_tracking;
    if (active <= 0) {
        fprintf(stderr, "btrc: unbalanced destroyed tracking scope\n");
        exit(1);
    }
    active--;
    __btrc_tracking = active;
    if (active == 0) {
        __btrc_destroyed_count = 0;
        if (__btrc_arc_active_unwinds <= 0) {
            fprintf(stderr, "btrc: invalid active unwind count\n");
            exit(1);
        }
        __btrc_arc_active_unwinds--;
    }
    __btrc_arc_unlock_mutation();
}""",
        depends_on=[
            "__btrc_destroyed_tracking",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_active_unwinds_state",
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
        c_source="static _Thread_local int __btrc_destroyed_cap = 0;",
    ),
    "__btrc_mark_destroyed": HelperDef(
        c_source=r"""static void __btrc_mark_destroyed(void* ptr) {
    if (!ptr) return;
    __btrc_arc_lock_mutation();
    if (!__btrc_tracking) {
        __btrc_arc_unlock_mutation();
        return;
    }
    if (__btrc_destroyed_count < 0 || __btrc_destroyed_cap < 0
            || __btrc_destroyed_count > __btrc_destroyed_cap) {
        fprintf(stderr, "btrc: invalid destroyed tracking capacity\n");
        exit(1);
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
        size_t bytes = sizeof(void*) * (size_t)new_cap;
        __btrc_destroyed = (void**)__btrc_safe_realloc(
            __btrc_destroyed, bytes);
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
    **ARC_SUSPECT_HELPERS,
}

__all__ = ["ARC_STATE_HELPERS"]
