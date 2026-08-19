/* btrc-runtime-helper:begin __btrc_arc_callback_types */
/* Type-erased ARC metadata shared by ownership paths. */
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
};
/* btrc-runtime-helper:end __btrc_arc_callback_types */
/* btrc-runtime-helper:begin __btrc_arc_header_of */
static inline __btrc_arc_header* __btrc_arc_header_of(void* object) {
    return (__btrc_arc_header*)object;
}
/* btrc-runtime-helper:end __btrc_arc_header_of */
/* btrc-runtime-helper:begin __btrc_arc_type_of */
static inline const __btrc_arc_type* __btrc_arc_type_of(
        void* object, const __btrc_arc_type* fallback) {
    if (object && __btrc_arc_header_of(object)->type)
        return __btrc_arc_header_of(object)->type;
    return fallback;
}
/* btrc-runtime-helper:end __btrc_arc_type_of */
/* btrc-runtime-helper:begin __btrc_arc_validate */
static inline void __btrc_arc_validate(void* object) {
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
}
/* btrc-runtime-helper:end __btrc_arc_validate */
/* btrc-runtime-helper:begin __btrc_destroyed_tracking */
/* ARC cascade-destroy tracking: avoid reading freed memory */
static _Thread_local int __btrc_tracking = 0;
static _Thread_local void** __btrc_destroyed = NULL;
static _Thread_local int __btrc_destroyed_count = 0;
/* btrc-runtime-helper:end __btrc_destroyed_tracking */
/* btrc-runtime-helper:begin __btrc_destroyed_tracking_scope */
static void __btrc_destroyed_tracking_begin(void) {
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
}
/* btrc-runtime-helper:end __btrc_destroyed_tracking_scope */
/* btrc-runtime-helper:begin __btrc_is_destroyed */
static int __btrc_is_destroyed(void* ptr) {
    if (!ptr) return 0;
    __btrc_arc_lock_mutation();
    for (int i = 0; i < __btrc_destroyed_count; i++) {
        if (__btrc_destroyed[i] != ptr) continue;
        __btrc_arc_unlock_mutation();
        return 1;
    }
    __btrc_arc_unlock_mutation();
    return 0;
}
/* btrc-runtime-helper:end __btrc_is_destroyed */
/* btrc-runtime-helper:begin __btrc_destroyed_capacity */
static _Thread_local int __btrc_destroyed_cap = 0;
/* btrc-runtime-helper:end __btrc_destroyed_capacity */
/* btrc-runtime-helper:begin __btrc_mark_destroyed */
static void __btrc_mark_destroyed(void* ptr) {
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
}
/* btrc-runtime-helper:end __btrc_mark_destroyed */
/* btrc-runtime-helper:begin __btrc_suspect_state */
/* ARC cycle detection: suspect buffer */
static void** __btrc_suspects = NULL;
static int __btrc_suspect_count = 0;
static __btrc_visit_fn* __btrc_visit_table = NULL;
static __btrc_destroy_fn* __btrc_destroy_table = NULL;
static void** __btrc_suspect_keys = NULL;
static int __btrc_suspect_key_cap = 0;
/* btrc-runtime-helper:end __btrc_suspect_state */
/* btrc-runtime-helper:begin __btrc_suspect_capacity */
static int __btrc_suspect_cap = 0;
/* btrc-runtime-helper:end __btrc_suspect_capacity */
/* btrc-runtime-helper:begin __btrc_ptr_hash */
static size_t __btrc_ptr_hash(const void* ptr) {
    uintptr_t value = (uintptr_t)ptr;
    value ^= value >> 17;
    value ^= value >> 9;
    return (size_t)value;
}
/* btrc-runtime-helper:end __btrc_ptr_hash */
/* btrc-runtime-helper:begin __btrc_suspect_locked */
static int __btrc_suspect_next_capacity(
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
}
/* btrc-runtime-helper:end __btrc_suspect_locked */
/* btrc-runtime-helper:begin __btrc_suspect */
static inline void __btrc_suspect(
        void* obj, __btrc_visit_fn visit, __btrc_destroy_fn destroy) {
    __btrc_arc_lock_mutation();
    __btrc_suspect_locked(obj, visit, destroy);
    __btrc_arc_unlock_mutation();
}
/* btrc-runtime-helper:end __btrc_suspect */
/* btrc-runtime-helper:begin __btrc_arc_lock_state */
/* One process-wide lock domain for ARC topology. */
static atomic_flag __btrc_arc_lock_flag = ATOMIC_FLAG_INIT;

static void __btrc_arc_lock_raw(void) {
    while (atomic_flag_test_and_set_explicit(
            &__btrc_arc_lock_flag, memory_order_acquire)) {}
}
static void __btrc_arc_unlock_raw(void) {
    atomic_flag_clear_explicit(
        &__btrc_arc_lock_flag, memory_order_release);
}
/* btrc-runtime-helper:end __btrc_arc_lock_state */
/* btrc-runtime-helper:begin __btrc_arc_shutdown_state */
static int __btrc_arc_shutdown = 0;
/* btrc-runtime-helper:end __btrc_arc_shutdown_state */
/* btrc-runtime-helper:begin __btrc_arc_active_drains_state */
static int __btrc_arc_active_drains = 0;
/* btrc-runtime-helper:end __btrc_arc_active_drains_state */
/* btrc-runtime-helper:begin __btrc_arc_active_unwinds_state */
static int __btrc_arc_active_unwinds = 0;
/* btrc-runtime-helper:end __btrc_arc_active_unwinds_state */
/* btrc-runtime-helper:begin __btrc_arc_snapshot_state */
static _Atomic int __btrc_arc_snapshotting = 0;
/* btrc-runtime-helper:end __btrc_arc_snapshot_state */
/* btrc-runtime-helper:begin __btrc_arc_mutation_lock */
static void __btrc_arc_lock_mutation(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire))
            return;
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
}
static void __btrc_arc_unlock_mutation(void) {
    __btrc_arc_unlock_raw();
}
/* btrc-runtime-helper:end __btrc_arc_mutation_lock */
/* btrc-runtime-helper:begin __btrc_arc_topology_state */
static int __btrc_arc_topology_active = 0;
static int __btrc_arc_topology_flush_pending = 0;
/* btrc-runtime-helper:end __btrc_arc_topology_state */
/* btrc-runtime-helper:begin __btrc_arc_topology_depth_state */
static _Thread_local int __btrc_arc_topology_depth = 0;
static _Thread_local int __btrc_arc_draining = 0;
/* btrc-runtime-helper:end __btrc_arc_topology_depth_state */
/* btrc-runtime-helper:begin __btrc_arc_topology_begin */
static void* __btrc_arc_topology_begin(void) {
    if (__btrc_arc_topology_depth > 0) {
        if (__btrc_arc_topology_depth == INT_MAX) {
            fprintf(stderr, "btrc: ARC topology scope overflow\n");
            exit(1);
        }
        __btrc_arc_topology_depth++;
        return (void*)&__btrc_arc_topology_active;
    }
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire)
                && !atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                && (!__btrc_arc_topology_flush_pending
                    || __btrc_arc_draining)) {
            if (__btrc_arc_topology_active == INT_MAX) {
                fprintf(stderr, "btrc: ARC topology scope overflow\n");
                exit(1);
            }
            __btrc_arc_topology_active++;
            __btrc_arc_topology_depth = 1;
            __btrc_arc_unlock_raw();
            return (void*)&__btrc_arc_topology_active;
        }
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
}
/* btrc-runtime-helper:end __btrc_arc_topology_begin */
/* btrc-runtime-helper:begin __btrc_arc_topology_leave */
static int __btrc_arc_topology_leave(void* token) {
    if (!token) return 0;
    if (token != (void*)&__btrc_arc_topology_active
            || __btrc_arc_topology_depth <= 0) {
        fprintf(stderr, "btrc: invalid ARC topology scope\n");
        exit(1);
    }
    __btrc_arc_topology_depth--;
    if (__btrc_arc_topology_depth > 0) return 0;
    __btrc_arc_lock_raw();
    if (__btrc_arc_shutdown) {
        __btrc_arc_unlock_raw();
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    if (__btrc_arc_topology_active <= 0) {
        fprintf(stderr, "btrc: invalid ARC topology scope\n");
        exit(1);
    }
    __btrc_arc_topology_active--;
    int should_flush = __btrc_arc_topology_active == 0
        && __btrc_arc_topology_flush_pending;
    __btrc_arc_unlock_raw();
    return should_flush;
}
/* btrc-runtime-helper:end __btrc_arc_topology_leave */
/* btrc-runtime-helper:begin __btrc_arc_topology_cleanup */
static void __btrc_arc_topology_cleanup(void* token) {
    int should_flush = __btrc_arc_topology_leave(token);
    __btrc_arc_drain_pending_abandons();
    if (should_flush)
        (void)__btrc_flush_cycles();
    __btrc_arc_drain_deferred(0);
}
/* btrc-runtime-helper:end __btrc_arc_topology_cleanup */
/* btrc-runtime-helper:begin __btrc_arc_topology_complete */
static void __btrc_arc_topology_complete(
        void* volatile* token_ref) {
    if (!token_ref || !*token_ref) return;
    void* token = *token_ref;
    *token_ref = NULL;
    int should_flush = __btrc_arc_topology_leave(token);
    __btrc_arc_drain_pending_abandons();
    if (should_flush)
        (void)__btrc_flush_cycles();
    __btrc_arc_drain_deferred(0);
}
/* btrc-runtime-helper:end __btrc_arc_topology_complete */
/* btrc-runtime-helper:begin __btrc_arc_deferred_state */
/* Per-thread intrusive FIFO for terminal ARC work. */
static _Thread_local void* __btrc_arc_deferred_head = NULL;
static _Thread_local void* __btrc_arc_deferred_tail = NULL;

static _Noreturn void __btrc_arc_raise_unlocked(
        const __btrc_arc_type* type, const char* message) {
    if (type && type->raise) type->raise(message);
    fprintf(stderr, "Unhandled exception: %s\n", message);
    exit(1);
}

static void __btrc_arc_enqueue_locked(void* object) {
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE
            || header->rc != 0 || header->edge_rc != 0
            || header->incoming != NULL || header->deferred_next != NULL) {
        fprintf(stderr, "btrc: invalid ARC enqueue\n");
        exit(1);
    }
    header->live_witness = NULL;
    header->state = __BTRC_ARC_QUEUED;
    if (__btrc_arc_deferred_tail) {
        __btrc_arc_header_of(__btrc_arc_deferred_tail)->deferred_next = object;
    } else {
        __btrc_arc_deferred_head = object;
    }
    __btrc_arc_deferred_tail = object;
}
/* btrc-runtime-helper:end __btrc_arc_deferred_state */
/* btrc-runtime-helper:begin __btrc_arc_snapshot_gate_state */
/* Publish snapshot intent before waiting for topology owners. */
static _Atomic int __btrc_arc_snapshot_pending = 0;
/* btrc-runtime-helper:end __btrc_arc_snapshot_gate_state */
/* btrc-runtime-helper:begin __btrc_arc_exclusive_snapshot */
static void __btrc_arc_exclusive_snapshot_begin(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (__btrc_arc_topology_depth != 0) {
            fprintf(stderr, "btrc: ARC snapshot inside topology mutation\n");
            exit(1);
        }
        if (!atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                && !atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {
            atomic_store_explicit(
                &__btrc_arc_snapshot_pending, 1, memory_order_release);
            __btrc_arc_unlock_raw();
            break;
        }
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {}
    }
    for (;;) {
        __btrc_arc_lock_raw();
        if (__btrc_arc_shutdown) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (__btrc_arc_topology_active == 0) {
            atomic_store_explicit(
                &__btrc_arc_snapshotting, 1, memory_order_release);
            atomic_store_explicit(
                &__btrc_arc_snapshot_pending, 0, memory_order_release);
            __btrc_arc_unlock_raw();
            return;
        }
        __btrc_arc_unlock_raw();
    }
}

static void __btrc_arc_exclusive_snapshot_end(void) {
    __btrc_arc_lock_raw();
    if (!atomic_load_explicit(
            &__btrc_arc_snapshotting, memory_order_acquire)) {
        fprintf(stderr, "btrc: invalid ARC snapshot completion\n");
        exit(1);
    }
    atomic_store_explicit(
        &__btrc_arc_snapshotting, 0, memory_order_release);
    __btrc_arc_unlock_raw();
}
/* btrc-runtime-helper:end __btrc_arc_exclusive_snapshot */
/* btrc-runtime-helper:begin __btrc_arc_reverse_state */
/* Scratch state for exact reverse-root classification. */
static void** __btrc_reverse_queue = NULL;
static int __btrc_reverse_queue_cap = 0;
static void** __btrc_reverse_keys = NULL;
static unsigned int* __btrc_reverse_marks = NULL;
static int __btrc_reverse_key_cap = 0;
static int __btrc_reverse_count = 0;
static unsigned int __btrc_reverse_epoch = 0;
/* btrc-runtime-helper:end __btrc_arc_reverse_state */
/* btrc-runtime-helper:begin __btrc_arc_register_incoming */
static void __btrc_arc_register_incoming(
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
}
/* btrc-runtime-helper:end __btrc_arc_register_incoming */
/* btrc-runtime-helper:begin __btrc_arc_unregister_incoming */
static void __btrc_arc_unregister_incoming(
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
}
/* btrc-runtime-helper:end __btrc_arc_unregister_incoming */
/* btrc-runtime-helper:begin __btrc_arc_incoming_teardown_pending */
static int __btrc_arc_incoming_teardown_pending(
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
}
/* btrc-runtime-helper:end __btrc_arc_incoming_teardown_pending */
/* btrc-runtime-helper:begin __btrc_arc_reverse_proves_live */
static int __btrc_reverse_next_capacity(
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
}
/* btrc-runtime-helper:end __btrc_arc_reverse_proves_live */
/* btrc-runtime-helper:begin __btrc_arc_retain */
static inline int __btrc_arc_retain(void* object) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* type = header->type;
    if (header->state != __BTRC_ARC_LIVE) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot retain destroying managed object");
    }
    if (header->rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    if (header->live_witness == object) header->live_witness = NULL;
    header->rc++;
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_retain */
/* btrc-runtime-helper:begin __btrc_arc_retain_edge */
static inline int __btrc_arc_retain_edge(
        void* object, void* owner) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* error_type = header->type;
    if (header->state != __BTRC_ARC_LIVE
            || (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)) {
        if (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)
            error_type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
    }
    if (header->rc == INT_MAX || header->edge_rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    __btrc_arc_register_incoming(object, owner);
    header->rc++;
    header->edge_rc++;
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_retain_edge */
/* btrc-runtime-helper:begin __btrc_arc_adopt_edge */
static inline int __btrc_arc_adopt_edge(
        void* object, void* owner) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* error_type = header->type;
    if (header->state != __BTRC_ARC_LIVE
            || (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)) {
        if (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)
            error_type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
    }
    if (header->edge_rc == INT_MAX || header->edge_rc >= header->rc) { fprintf(stderr, "btrc: invalid owned-edge adoption\n"); exit(1); }
    __btrc_arc_register_incoming(object, owner);
    header->edge_rc++;
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_adopt_edge */
/* btrc-runtime-helper:begin __btrc_arc_unlink_edge */
static inline int __btrc_arc_unlink_edge(
        void* object, void* owner) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE
            || (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE
                && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_DESTROYING)) {
        const __btrc_arc_type* type = header->type;
        if (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE
                && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_DESTROYING)
            type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot retain destroying managed object");
    }
    __btrc_arc_unregister_incoming(object, owner);
    __btrc_arc_unlock_mutation();
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_unlink_edge */
/* btrc-runtime-helper:begin __btrc_forget_suspect */
static void __btrc_forget_suspect(void* obj) {
    if (!obj || __btrc_suspect_key_cap == 0) return;
    size_t mask = (size_t)__btrc_suspect_key_cap - 1;
    size_t hole = __btrc_ptr_hash(obj) & mask;
    while (__btrc_suspect_keys[hole]
            && __btrc_suspect_keys[hole] != obj)
        hole = (hole + 1) & mask;
    if (!__btrc_suspect_keys[hole]) return;
    __btrc_suspect_keys[hole] = NULL;
    size_t scan = (hole + 1) & mask;
    while (__btrc_suspect_keys[scan]) {
        void* displaced = __btrc_suspect_keys[scan];
        __btrc_suspect_keys[scan] = NULL;
        size_t target = __btrc_ptr_hash(displaced) & mask;
        while (__btrc_suspect_keys[target])
            target = (target + 1) & mask;
        __btrc_suspect_keys[target] = displaced;
        scan = (scan + 1) & mask;
    }
    for (int i = 0; i < __btrc_suspect_count; i++) {
        if (__btrc_suspects[i] != obj) continue;
        int last = --__btrc_suspect_count;
        if (i != last) {
            __btrc_suspects[i] = __btrc_suspects[last];
            __btrc_visit_table[i] = __btrc_visit_table[last];
            __btrc_destroy_table[i] = __btrc_destroy_table[last];
        }
        return;
    }
}
/* btrc-runtime-helper:end __btrc_forget_suspect */
/* btrc-runtime-helper:begin __btrc_arc_release_impl */
static inline int __btrc_arc_release_impl(
        void* object, const __btrc_arc_type* fallback,
        int edge, void* replacement) {
    if (!object) return 0;
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy) { fprintf(stderr, "btrc: untyped managed release\n"); exit(1); }
    if (header->state != __BTRC_ARC_LIVE) {
        fprintf(stderr, "btrc: release of non-live managed object\n");
        exit(1);
    }
    if (header->rc <= 0 || (edge && header->edge_rc <= 0)) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
    if (edge) {
        /* The slot-specific unlink atom invalidated only the removed owner. */
        (void)replacement;
        header->edge_rc--;
    }
    header->rc--;
    if (header->rc == 0) {
        if (header->edge_rc != 0 || header->incoming != NULL) {
            fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
            exit(1);
        }
        __btrc_forget_suspect(object);
        __btrc_arc_enqueue_locked(object);
        return 0;
    }
    __btrc_arc_validate(object);
    if (type->visit && header->rc == header->edge_rc
            && !__btrc_arc_incoming_teardown_pending(object)
            && !__btrc_arc_reverse_proves_live(object))
        __btrc_suspect_locked(object, type->visit, type->destroy);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release_impl */
/* btrc-runtime-helper:begin __btrc_arc_replace_edge */
static inline int __btrc_arc_replace_edge(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access,
        void* replacement, void* owner,
        const __btrc_arc_type* fallback, int adopt) {
    if (!slot_storage || !access || !owner) {
        fprintf(stderr, "btrc: managed edge replacement requires a slot and owner\n");
        exit(1);
    }
    __btrc_arc_lock_mutation();
    void* object = access(slot_storage, NULL, NULL, 0);
    __btrc_arc_validate(owner);
    __btrc_arc_header* owner_header = __btrc_arc_header_of(owner);
    const __btrc_arc_type* error_type = owner_header->type;
    int invalid_publication = replacement
        && owner_header->state != __BTRC_ARC_LIVE;
    if (replacement) {
        __btrc_arc_validate(replacement);
        if (__btrc_arc_header_of(replacement)->state
                != __BTRC_ARC_LIVE) {
            invalid_publication = 1;
            error_type = __btrc_arc_header_of(replacement)->type;
        }
    }
    if (invalid_publication) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
        return -1;
    }
    if (!replacement && owner_header->state != __BTRC_ARC_LIVE
            && owner_header->state != __BTRC_ARC_DESTROYING) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
        return -1;
    }
    if (object == replacement) {
        if (replacement && adopt)
            __btrc_arc_release_impl(replacement, fallback, 0, NULL);
        __btrc_arc_unlock_mutation();
        __btrc_arc_drain_deferred(0);
        return 0;
    }
    if (access(slot_storage, object, replacement, 1) != object) {
        __btrc_arc_unlock_mutation();
        fprintf(stderr, "btrc: managed edge changed during transaction\n");
        exit(1);
    }
    if (object) {
        __btrc_arc_validate(object);
        __btrc_arc_unregister_incoming(object, owner);
    }
    if (replacement) {
        __btrc_arc_header* next = __btrc_arc_header_of(replacement);
        if (adopt) {
            if (next->edge_rc == INT_MAX || next->edge_rc >= next->rc) {
                fprintf(stderr, "btrc: invalid owned-edge adoption\n");
                exit(1);
            }
            __btrc_arc_register_incoming(replacement, owner);
            next->edge_rc++;
        } else {
            if (next->rc == INT_MAX || next->edge_rc == INT_MAX) {
                fprintf(stderr, "btrc: reference count overflow\n");
                exit(1);
            }
            __btrc_arc_register_incoming(replacement, owner);
            next->rc++;
            next->edge_rc++;
        }
        __btrc_arc_validate(replacement);
    }
    if (object)
        __btrc_arc_release_impl(object, fallback, 1, replacement);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_replace_edge */
/* btrc-runtime-helper:begin __btrc_arc_release */
static inline int __btrc_arc_release(
        void* object, const __btrc_arc_type* type) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_release_impl(object, type, 0, NULL);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release */
/* btrc-runtime-helper:begin __btrc_arc_release_edge */
static inline int __btrc_arc_release_edge(
        void* object, const __btrc_arc_type* type, void* replacement) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_release_impl(object, type, 1, replacement);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release_edge */
/* btrc-runtime-helper:begin __btrc_arc_release_acyclic */
static inline int __btrc_arc_release_acyclic(
        void* object, const __btrc_arc_type* type) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* runtime_type = __btrc_arc_type_of(object, type);
    if (!runtime_type || !runtime_type->destroy) { fprintf(stderr, "btrc: untyped managed release\n"); exit(1); }
    if (header->state != __BTRC_ARC_LIVE || header->rc <= 0) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
    header->rc--;
    if (header->rc == 0) {
        if (header->edge_rc != 0 || header->incoming != NULL) {
            fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
            exit(1);
        }
        __btrc_arc_enqueue_locked(object);
    } else {
        __btrc_arc_validate(object);
    }
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release_acyclic */
/* btrc-runtime-helper:begin __btrc_arc_invalidate */
static inline int __btrc_arc_invalidate(void* object) {
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_invalidate */
/* btrc-runtime-helper:begin __btrc_arc_destroy_slot */
static inline int __btrc_arc_destroy_slot(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access,
        const __btrc_arc_type* fallback) {
    if (!slot_storage || !access) return 0;
    __btrc_arc_lock_mutation();
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) {
        __btrc_arc_unlock_mutation();
        return 0;
    }
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy) { fprintf(stderr, "btrc: untyped managed destroy\n"); exit(1); }
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE || header->rc != 1
            || header->edge_rc != 0 || header->incoming != NULL) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot delete shared managed object");
    }
    if (access(slot_storage, object, NULL, 1) != object) {
        __btrc_arc_unlock_mutation();
        fprintf(stderr, "btrc: managed delete slot changed during transaction\n");
        exit(1);
    }
    header->rc = 0;
    header->live_witness = NULL;
    __btrc_forget_suspect(object);
    __btrc_arc_enqueue_locked(object);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_destroy_slot */
/* btrc-runtime-helper:begin __btrc_arc_destroy_edge */
static inline int __btrc_arc_destroy_edge(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access, void* owner,
        const __btrc_arc_type* fallback) {
    if (!slot_storage || !access || !owner) return 0;
    __btrc_arc_lock_mutation();
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) {
        __btrc_arc_unlock_mutation();
        return 0;
    }
    __btrc_arc_validate(owner);
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    __btrc_arc_header* owner_header = __btrc_arc_header_of(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    int owner_valid = owner_header->state == __BTRC_ARC_LIVE
        || owner_header->state == __BTRC_ARC_DESTROYING;
    int unique = header->state == __BTRC_ARC_LIVE
        && header->rc == 1 && header->edge_rc == 1
        && header->incoming && header->incoming->owner == owner
        && header->incoming->next == NULL;
    if (!owner_valid || !unique) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot delete shared managed object");
    }
    if (access(slot_storage, object, NULL, 1) != object) {
        __btrc_arc_unlock_mutation();
        fprintf(stderr, "btrc: managed delete slot changed during transaction\n");
        exit(1);
    }
    __btrc_arc_unregister_incoming(object, owner);
    header->rc = 0;
    header->edge_rc = 0;
    header->live_witness = NULL;
    __btrc_forget_suspect(object);
    __btrc_arc_enqueue_locked(object);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_destroy_edge */
/* btrc-runtime-helper:begin __btrc_cycle_collector_state */

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

/* btrc-runtime-helper:end __btrc_cycle_collector_state */
/* btrc-runtime-helper:begin __btrc_arc_graph_primitives */

static void __btrc_cycle_fail(const char* message) {
    fprintf(stderr, "btrc: %s\n", message);
    exit(1);
}
static int __btrc_cycle_next_capacity(
        int capacity, const char* message) {
    if (capacity < 0 || capacity > INT_MAX / 2)
        __btrc_cycle_fail(message);
    return capacity ? capacity * 2 : 256;
}
static size_t __btrc_cycle_capacity_bytes(
        int capacity, size_t element_size, const char* message) {
    if (capacity < 0 || (element_size != 0
            && (size_t)capacity > SIZE_MAX / element_size))
        __btrc_cycle_fail(message);
    return (size_t)capacity * element_size;
}
static void __btrc_cycle_next_epoch(
        unsigned int* epoch, unsigned int* marks, int cap) {
    (*epoch)++;
    if (*epoch == 0) {
        if (marks) {
            size_t bytes = __btrc_cycle_capacity_bytes(
                cap, sizeof(unsigned int), "cycle epoch size overflow");
            memset(marks, 0, bytes);
        }
        *epoch = 1;
    }
}
static void __btrc_cycle_reserve_vertices(
        __btrc_cycle_context* context, int needed) {
    if (needed < 0 || context->vertex_cap < 0)
        __btrc_cycle_fail("cycle vertex overflow");
    if (needed <= context->vertex_cap) return;
    int cap = context->vertex_cap;
    while (cap < needed)
        cap = __btrc_cycle_next_capacity(cap, "cycle vertex overflow");
    size_t bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(__btrc_cycle_vertex), "cycle vertex size overflow");
    context->vertices = (__btrc_cycle_vertex*)__btrc_safe_realloc(
        context->vertices, bytes);
    context->vertex_cap = cap;
}
static void __btrc_cycle_reserve_edges(
        __btrc_cycle_context* context, int needed) {
    if (needed < 0 || context->edge_cap < 0)
        __btrc_cycle_fail("cycle edge overflow");
    if (needed <= context->edge_cap) return;
    int cap = context->edge_cap;
    while (cap < needed)
        cap = __btrc_cycle_next_capacity(cap, "cycle edge overflow");
    size_t bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(__btrc_cycle_edge), "cycle edge size overflow");
    context->edges = (__btrc_cycle_edge*)__btrc_safe_realloc(
        context->edges, bytes);
    context->edge_cap = cap;
}
static void __btrc_cycle_reserve_queue(
        __btrc_cycle_context* context, int needed) {
    if (needed < 0 || context->queue_cap < 0)
        __btrc_cycle_fail("cycle queue overflow");
    if (needed <= context->queue_cap) return;
    int cap = context->queue_cap;
    while (cap < needed)
        cap = __btrc_cycle_next_capacity(cap, "cycle queue overflow");
    size_t bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(int), "cycle queue size overflow");
    context->queue = (int*)__btrc_safe_realloc(
        context->queue, bytes);
    context->queue_cap = cap;
}
static void __btrc_cycle_push_queue(
        __btrc_cycle_context* context, int value) {
    if (context->queue_count < 0 || context->queue_count == INT_MAX)
        __btrc_cycle_fail("cycle queue overflow");
    __btrc_cycle_reserve_queue(context, context->queue_count + 1);
    context->queue[context->queue_count++] = value;
}
static void __btrc_cycle_grow_objects(__btrc_cycle_context* context) {
    int cap = __btrc_cycle_next_capacity(
        context->object_cap, "cycle object hash overflow");
    size_t key_bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(void*), "cycle object hash size overflow");
    size_t value_bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(int), "cycle object hash size overflow");
    size_t mark_bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(unsigned int), "cycle object hash size overflow");
    void** keys = (void**)__btrc_safe_calloc(1, key_bytes);
    int* values = (int*)__btrc_safe_realloc(NULL, value_bytes);
    unsigned int* marks = (unsigned int*)__btrc_safe_calloc(1, mark_bytes);
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
    if (context->vertex_count < 0 || context->vertex_count == INT_MAX)
        __btrc_cycle_fail("cycle vertex overflow");
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
    int cap = __btrc_cycle_next_capacity(
        context->slot_cap, "cycle slot hash overflow");
    size_t key_bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(volatile void*), "cycle slot hash size overflow");
    size_t value_bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(int), "cycle slot hash size overflow");
    size_t mark_bytes = __btrc_cycle_capacity_bytes(
        cap, sizeof(unsigned int), "cycle slot hash size overflow");
    volatile void** keys = (volatile void**)__btrc_safe_calloc(
        1, key_bytes);
    int* values = (int*)__btrc_safe_realloc(NULL, value_bytes);
    unsigned int* marks = (unsigned int*)__btrc_safe_calloc(1, mark_bytes);
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

/* btrc-runtime-helper:end __btrc_arc_graph_primitives */
/* btrc-runtime-helper:begin __btrc_arc_abandon_graph */
static void __btrc_abandon_snapshot_edge(
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
}
/* btrc-runtime-helper:end __btrc_arc_abandon_graph */
/* btrc-runtime-helper:begin __btrc_arc_abandon_callback_state */
typedef void (*__btrc_abandon_drain_fn)(void);
static _Thread_local __btrc_abandon_drain_fn
    __btrc_abandon_drain_callback = NULL;
/* btrc-runtime-helper:end __btrc_arc_abandon_callback_state */
/* btrc-runtime-helper:begin __btrc_arc_abandon_queue_state */
static _Thread_local void** __btrc_abandon_queue = NULL;
static _Thread_local int __btrc_abandon_count = 0;
static _Thread_local int __btrc_abandon_cap = 0;
/* btrc-runtime-helper:end __btrc_arc_abandon_queue_state */
/* btrc-runtime-helper:begin __btrc_arc_abandon_queue_drain */
static void __btrc_arc_drain_pending_abandons(void) {
    __btrc_abandon_drain_fn callback =
        __btrc_abandon_drain_callback;
    if (callback) callback();
}
/* btrc-runtime-helper:end __btrc_arc_abandon_queue_drain */
/* btrc-runtime-helper:begin __btrc_arc_abandon */
static void __btrc_arc_drain_abandon_queue(void) {
    if (__btrc_arc_topology_depth != 0) return;
    for (;;) {
        __btrc_arc_lock_mutation();
        void** batch = __btrc_abandon_queue;
        int count = __btrc_abandon_count;
        __btrc_abandon_queue = NULL;
        __btrc_abandon_count = 0;
        __btrc_abandon_cap = 0;
        __btrc_abandon_drain_callback = NULL;
        __btrc_arc_unlock_mutation();
        if (count == 0) {
            free(batch);
            break;
        }
        __btrc_arc_abandon_many(batch, count, 1);
    }
}

static void __btrc_arc_abandon(void* object) {
    if (!object) return;
    if (__btrc_arc_topology_depth == 0) {
        __btrc_arc_abandon_now(object);
        return;
    }
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE) {
        fprintf(stderr, "btrc: invalid deferred construction abandon\n");
        exit(1);
    }
    if (__btrc_abandon_count < 0 || __btrc_abandon_cap < 0
            || __btrc_abandon_count > __btrc_abandon_cap) {
        fprintf(stderr, "btrc: invalid construction abandon capacity\n");
        exit(1);
    }
    for (int i = 0; i < __btrc_abandon_count; i++) {
        if (__btrc_abandon_queue[i] == object) {
            fprintf(stderr, "btrc: duplicate deferred construction abandon\n");
            exit(1);
        }
    }
    if (__btrc_abandon_count == INT_MAX) {
        fprintf(stderr, "btrc: construction abandon queue overflow\n");
        exit(1);
    }
    if (__btrc_abandon_count >= __btrc_abandon_cap) {
        if (__btrc_abandon_cap > INT_MAX / 2) {
            fprintf(stderr, "btrc: construction abandon capacity overflow\n");
            exit(1);
        }
        int cap = __btrc_abandon_cap
            ? __btrc_abandon_cap * 2 : 16;
        if ((size_t)cap > SIZE_MAX / sizeof(void*)) {
            fprintf(stderr, "btrc: construction abandon size overflow\n");
            exit(1);
        }
        size_t bytes = sizeof(void*) * (size_t)cap;
        __btrc_abandon_queue = (void**)__btrc_safe_realloc(
            __btrc_abandon_queue, bytes);
        __btrc_abandon_cap = cap;
    }
    __btrc_abandon_queue[__btrc_abandon_count++] = object;
    __btrc_abandon_drain_callback =
        __btrc_arc_drain_abandon_queue;
    __btrc_arc_topology_flush_pending = 1;
    __btrc_arc_unlock_mutation();
}
/* btrc-runtime-helper:end __btrc_arc_abandon */
/* btrc-runtime-helper:begin __btrc_collect_cycles_once */
static void __btrc_cycle_snapshot_edge(
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

/* btrc-runtime-helper:end __btrc_collect_cycles_once */
/* btrc-runtime-helper:begin __btrc_arc_drain */
static void __btrc_arc_drain_deferred(int force_cycles) {
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
}
/* btrc-runtime-helper:end __btrc_arc_drain */
/* btrc-runtime-helper:begin __btrc_collect_cycles */
static void __btrc_collect_cycles(void) {
    __btrc_arc_drain_deferred(1);
}
/* btrc-runtime-helper:end __btrc_collect_cycles */
/* btrc-runtime-helper:begin __btrc_poll_cycles */
static inline int __btrc_poll_cycles(void) {
    __btrc_arc_lock_mutation();
    int pending = __btrc_suspect_count >= 256;
    __btrc_arc_unlock_mutation();
    if (pending) __btrc_arc_drain_deferred(1);
    return 0;
}
/* btrc-runtime-helper:end __btrc_poll_cycles */
/* btrc-runtime-helper:begin __btrc_flush_cycles */
static int __btrc_flush_cycles(void) {
    __btrc_arc_drain_deferred(1);
    return 0;
}
/* btrc-runtime-helper:end __btrc_flush_cycles */
/* btrc-runtime-helper:begin __btrc_arc_thread_state_cleanup */
static void __btrc_arc_thread_state_finalize(void) {
    __btrc_arc_lock_mutation();
    if (__btrc_tracking != 0
            || __btrc_arc_topology_depth != 0
            || __btrc_arc_draining
            || __btrc_arc_deferred_head
            || __btrc_arc_deferred_tail
            || __btrc_abandon_queue
            || __btrc_abandon_count != 0
            || __btrc_abandon_drain_callback) {
        fprintf(stderr, "btrc: ARC thread cleanup during active work\n");
        exit(1);
    }
    free(__btrc_destroyed);
    __btrc_destroyed = NULL;
    __btrc_destroyed_count = 0;
    __btrc_destroyed_cap = 0;
    free(__btrc_abandon_queue);
    __btrc_abandon_queue = NULL;
    __btrc_abandon_count = 0;
    __btrc_abandon_cap = 0;
    __btrc_abandon_drain_callback = NULL;
    __btrc_arc_unlock_mutation();
}
static void __btrc_arc_thread_state_cleanup(void) {
    __btrc_arc_drain_pending_abandons();
    __btrc_arc_drain_deferred(1);
    __btrc_arc_thread_state_finalize();
}
/* btrc-runtime-helper:end __btrc_arc_thread_state_cleanup */
/* btrc-runtime-helper:begin __btrc_cycle_state_cleanup */
static inline void __btrc_cycle_state_cleanup(void) {
    __btrc_arc_thread_state_cleanup();
    __btrc_flush_cycles();
    __btrc_arc_lock_raw();
    if (__btrc_arc_shutdown) {
        __btrc_arc_unlock_raw();
        fprintf(stderr, "btrc: repeated ARC shutdown\n");
        exit(1);
    }
    __btrc_arc_shutdown = 1;
    if (__btrc_arc_active_drains != 0
            || __btrc_arc_active_unwinds != 0
            || atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire) != 0
            || atomic_load_explicit(
                &__btrc_arc_snapshot_pending, memory_order_acquire) != 0
            || __btrc_collecting != 0) {
        fprintf(stderr, "btrc: ARC cleanup during active work\n");
        exit(1);
    }
    if (__btrc_arc_topology_active != 0) {
        fprintf(stderr, "btrc: ARC cleanup during topology mutation\n");
        exit(1);
    }
    free(__btrc_suspects);
    free(__btrc_visit_table);
    free(__btrc_destroy_table);
    free(__btrc_suspect_keys);
    free(__btrc_reverse_queue);
    free(__btrc_reverse_keys);
    free(__btrc_reverse_marks);
    free(__btrc_cycle_scratch.vertices);
    free(__btrc_cycle_scratch.edges);
    free(__btrc_cycle_scratch.queue);
    free(__btrc_cycle_scratch.object_keys);
    free(__btrc_cycle_scratch.object_values);
    free(__btrc_cycle_scratch.object_marks);
    free(__btrc_cycle_scratch.slot_keys);
    free(__btrc_cycle_scratch.slot_values);
    free(__btrc_cycle_scratch.slot_marks);
    memset(&__btrc_cycle_scratch, 0, sizeof(__btrc_cycle_scratch));
    __btrc_suspects = NULL;
    __btrc_visit_table = NULL;
    __btrc_destroy_table = NULL;
    __btrc_suspect_keys = NULL;
    __btrc_reverse_queue = NULL;
    __btrc_reverse_keys = NULL;
    __btrc_reverse_marks = NULL;
    __btrc_suspect_count = __btrc_suspect_cap = 0;
    __btrc_suspect_key_cap = 0;
    __btrc_reverse_queue_cap = __btrc_reverse_key_cap = 0;
    __btrc_reverse_count = 0;
    __btrc_reverse_epoch = 0;
    if (__btrc_arc_deferred_head || __btrc_arc_deferred_tail
            || __btrc_arc_draining) {
        fprintf(stderr, "btrc: ARC cleanup during active drain\n");
        exit(1);
    }
    __btrc_arc_topology_flush_pending = 0;
    __btrc_collecting = 0;
    __btrc_arc_unlock_raw();
}
/* btrc-runtime-helper:end __btrc_cycle_state_cleanup */
