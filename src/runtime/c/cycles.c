/* btrc-runtime-helper:begin __btrc_arc_callback_types */
/* Type-erased ARC metadata shared by ownership paths. */
typedef _Atomic int __btrc_arc_count;
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
    _Atomic(void*) live_witness;
    const __btrc_arc_type* type;
    __btrc_arc_incoming* incoming;
    void* deferred_next;
    unsigned char suppress_hook;
    _Atomic unsigned char in_suspects;
    /* Bit 15: per-object edge spinlock; bits 0..14: active witness-walk pins. */
    _Atomic unsigned short pin_lock;
    _Atomic int state;
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
typedef struct {
    const char* name;
    const void* methods;
} __btrc_interface_entry;
struct __btrc_arc_type {
    __btrc_visit_fn visit;
    __btrc_destroy_fn destroy;
    __btrc_hook_fn hook;
    __btrc_hook_guard_fn guard;
    __btrc_raise_fn raise;
    const __btrc_interface_entry* interfaces;
    size_t interface_count;
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
/* btrc-runtime-helper:begin __btrc_interface_try_methods */
static inline const void* __btrc_interface_try_methods(void* object, const char* name) {
    const __btrc_arc_type* type = __btrc_arc_type_of(object, NULL);
    size_t first = 0;
    size_t last = type ? type->interface_count : 0;
    while (first < last) {
        size_t middle = first + (last - first) / 2;
        int order = strcmp(type->interfaces[middle].name, name);
        if (order == 0) return type->interfaces[middle].methods;
        if (order < 0) first = middle + 1;
        else last = middle;
    }
    return NULL;
}
/* btrc-runtime-helper:end __btrc_interface_try_methods */
/* btrc-runtime-helper:begin __btrc_interface_methods */
static inline const void* __btrc_interface_methods(void* object, const char* name) {
    const void* methods = __btrc_interface_try_methods(object, name);
    if (methods) return methods;
    fprintf(stderr, "btrc: invalid interface receiver for %s\n", name);
    abort();
}
/* btrc-runtime-helper:end __btrc_interface_methods */
/* btrc-runtime-helper:begin __btrc_arc_validate */
/* Header invariants are checked on every retain, release and edge move.
 * That is a debugging aid, not a memory-safety boundary: the checks cost
 * about a twentieth of a compiled program's time, so they stay on under a
 * sanitizer or BTRC_ARC_CHECKS and are compiled out otherwise. */
#if defined(BTRC_ARC_CHECKS) || defined(__SANITIZE_ADDRESS__) || defined(__SANITIZE_THREAD__)
#define __BTRC_ARC_CHECKS 1
#elif defined(__has_feature)
#if __has_feature(address_sanitizer) || __has_feature(thread_sanitizer)
#define __BTRC_ARC_CHECKS 1
#endif
#endif
static inline void __btrc_arc_validate(void* object) {
#if !defined(__BTRC_ARC_CHECKS)
    (void)object;
    return;
#endif
    if (!object) return;
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    int state = atomic_load_explicit(&header->state, memory_order_acquire);
    int erc = atomic_load_explicit(&header->edge_rc, memory_order_acquire);
    int rc = atomic_load_explicit(&header->rc, memory_order_acquire);
    void* witness = atomic_load_explicit(&header->live_witness, memory_order_relaxed);
    int live = state == __BTRC_ARC_LIVE
        && rc > 0 && erc >= 0
        && erc <= rc
        && header->deferred_next == NULL && !header->suppress_hook;
    int queued = state == __BTRC_ARC_QUEUED
        && rc == 0 && erc == 0
        && witness == NULL && header->incoming == NULL;
    int destroying = state == __BTRC_ARC_DESTROYING
        && rc == 0 && erc == 0
        && witness == NULL && header->incoming == NULL
        && header->deferred_next == NULL && !header->suppress_hook;
    if ((!live && !queued && !destroying) || !header->type
            || !header->type->destroy
            || (header->type->hook
                && (!header->type->guard || !header->type->raise))) {
        fprintf(stderr, "btrc: invalid ARC header\n");
        exit(1);
    }
}

static inline void __btrc_arc_validate_unlocked(void* object) {
#if !defined(__BTRC_ARC_CHECKS)
    (void)object;
    return;
#endif
    if (!object) return;
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    int state = atomic_load_explicit(&header->state, memory_order_acquire);
    int rc = atomic_load_explicit(&header->rc, memory_order_acquire);
    int erc = atomic_load_explicit(&header->edge_rc, memory_order_acquire);
    int live = state == __BTRC_ARC_LIVE
        && rc > 0 && erc >= 0
        && header->deferred_next == NULL && !header->suppress_hook;
    int queued = state == __BTRC_ARC_QUEUED && rc == 0 && erc == 0;
    int destroying = state == __BTRC_ARC_DESTROYING
        && rc == 0 && erc == 0
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
/* __btrc_tls.tracking, __btrc_tls.destroyed and __btrc_tls.destroyed_count live in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_destroyed_tracking */
/* btrc-runtime-helper:begin __btrc_destroyed_tracking_scope */
static void __btrc_destroyed_tracking_begin(void) {
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    int active = __btrc_tls.tracking;
    if (active == 0) {
        __btrc_tls.destroyed_count = 0;
        size_t stripe = __btrc_arc_my_stripe();
        atomic_fetch_add_explicit(
            &__btrc_arc_shared.stripes[stripe].unwinds, 1, memory_order_relaxed);
    }
    if (active == INT_MAX) {
        fprintf(stderr, "btrc: destroyed tracking depth overflow\n");
        exit(1);
    }
    __btrc_tls.tracking = active + 1;
}
static void __btrc_destroyed_tracking_end(void) {
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    int active = __btrc_tls.tracking;
    if (active <= 0) {
        fprintf(stderr, "btrc: unbalanced destroyed tracking scope\n");
        exit(1);
    }
    active--;
    __btrc_tls.tracking = active;
    if (active == 0) {
        __btrc_tls.destroyed_count = 0;
        size_t stripe = __btrc_arc_my_stripe();
        if (atomic_fetch_sub_explicit(
                &__btrc_arc_shared.stripes[stripe].unwinds, 1, memory_order_relaxed) <= 0) {
            fprintf(stderr, "btrc: invalid active unwind count\n");
            exit(1);
        }
    }
}
/* btrc-runtime-helper:end __btrc_destroyed_tracking_scope */
/* btrc-runtime-helper:begin __btrc_is_destroyed */
static int __btrc_is_destroyed(void* ptr) {
    if (!ptr) return 0;
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    for (int i = 0; i < __btrc_tls.destroyed_count; i++) {
        if (__btrc_tls.destroyed[i] != ptr) continue;
        return 1;
    }
    return 0;
}
/* btrc-runtime-helper:end __btrc_is_destroyed */
/* btrc-runtime-helper:begin __btrc_destroyed_capacity */
/* __btrc_tls.destroyed_cap lives in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_destroyed_capacity */
/* btrc-runtime-helper:begin __btrc_mark_destroyed */
static void __btrc_mark_destroyed(void* ptr) {
    if (!ptr) return;
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    if (!__btrc_tls.tracking) return;
    if (__btrc_tls.destroyed_count < 0 || __btrc_tls.destroyed_cap < 0
            || __btrc_tls.destroyed_count > __btrc_tls.destroyed_cap) {
        fprintf(stderr, "btrc: invalid destroyed tracking capacity\n");
        exit(1);
    }
    for (int i = 0; i < __btrc_tls.destroyed_count; i++) {
        if (__btrc_tls.destroyed[i] != ptr) continue;
        return;
    }
    if (__btrc_tls.destroyed_count >= __btrc_tls.destroyed_cap) {
        if (__btrc_tls.destroyed_cap > INT_MAX / 2) { fprintf(stderr, "btrc: destroyed tracking overflow\n"); exit(1); }
        int new_cap = __btrc_tls.destroyed_cap ? __btrc_tls.destroyed_cap * 2 : 256;
        if ((size_t)new_cap > SIZE_MAX / sizeof(void*)) { fprintf(stderr, "btrc: destroyed tracking size overflow\n"); exit(1); }
        size_t bytes = sizeof(void*) * (size_t)new_cap;
        __btrc_tls.destroyed = (void**)__btrc_safe_realloc(
            __btrc_tls.destroyed, bytes);
        __btrc_tls.destroyed_cap = new_cap;
    }
    __btrc_tls.destroyed[__btrc_tls.destroyed_count++] = ptr;
}
/* btrc-runtime-helper:end __btrc_mark_destroyed */
/* btrc-runtime-helper:begin __btrc_suspect_state */
/* ARC cycle detection: suspect buffer */
static void** __btrc_suspects = NULL;
static int __btrc_suspect_count = 0;
static _Atomic int __btrc_suspect_count_atomic = 0;
static __btrc_visit_fn* __btrc_visit_table = NULL;
static __btrc_destroy_fn* __btrc_destroy_table = NULL;
static void** __btrc_suspect_keys = NULL;
/* Buffer index of the suspect held at each hash slot, so forgetting one never
 * scans the buffer. */
static int* __btrc_suspect_slots = NULL;
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
    size_t slot_bytes = __btrc_suspect_capacity_bytes(
        cap, sizeof(int), "cycle suspect hash size overflow");
    void** keys = (void**)__btrc_safe_calloc(1, bytes);
    int* slots = (int*)__btrc_safe_calloc(1, slot_bytes);
    for (int i = 0; i < __btrc_suspect_count; i++) {
        size_t index = __btrc_ptr_hash(__btrc_suspects[i]) & ((size_t)cap - 1);
        while (keys[index]) index = (index + 1) & ((size_t)cap - 1);
        keys[index] = __btrc_suspects[i];
        slots[index] = i;
    }
    free(__btrc_suspect_keys);
    free(__btrc_suspect_slots);
    __btrc_suspect_keys = keys;
    __btrc_suspect_slots = slots;
    __btrc_suspect_key_cap = cap;
}
static inline void __btrc_suspect_locked(void* obj, __btrc_visit_fn visit,
                           __btrc_destroy_fn destroy) {
    if (!obj) return;
    __btrc_arc_validate(obj);
    __btrc_arc_header* header = __btrc_arc_header_of(obj);
    if (atomic_load_explicit(&header->rc, memory_order_acquire)
            > atomic_load_explicit(&header->edge_rc, memory_order_acquire))
        return;
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
    __btrc_suspect_slots[key] = __btrc_suspect_count;
    __btrc_suspect_count++;
    atomic_store_explicit(&header->in_suspects, 1, memory_order_release);
    atomic_store_explicit(
        &__btrc_suspect_count_atomic, __btrc_suspect_count, memory_order_release);
}
/* btrc-runtime-helper:end __btrc_suspect_locked */
/* btrc-runtime-helper:begin __btrc_suspect */
static inline void __btrc_suspect(
        void* obj, __btrc_visit_fn visit, __btrc_destroy_fn destroy) {
    if (!obj) return;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_obj_lock(obj);
    __btrc_arc_suspect_lock();
    __btrc_suspect_locked(obj, visit, destroy);
    __btrc_arc_suspect_unlock();
    __btrc_arc_obj_unlock(obj);
    __btrc_arc_mutator_leave(stripe);
}
/* btrc-runtime-helper:end __btrc_suspect */
/* btrc-runtime-helper:begin __btrc_arc_lock_state */
/* Striped reader-writer snapshot gate + per-object inline header locks.
 *
 * Pure C11 stdatomic.h so --freestanding builds need no platform lock headers.
 * Lock order (strictly ascending):
 *   Level 0: Snapshot Gate (mutator stripe shared vs lock_raw + snapshotting exclusive)
 *   Level 1: Slot lock (__btrc_arc_shared.slot_locks[0..511], at most one)
 *   Level 2: Per-object header locks (header->pin_lock bit 15, ascending address order)
 *   Level 3: Suspect table lock (__btrc_arc_shared.suspect_lock) */
#define __BTRC_ARC_STRIPE_COUNT 64
#define __BTRC_ARC_SLOT_LOCK_STRIPES 512
#define __BTRC_ARC_OBJ_LOCK_BIT ((unsigned short)0x8000u)
#define __BTRC_ARC_PIN_MASK ((unsigned short)0x7FFFu)

typedef struct __btrc_arc_stripe {
    _Alignas(128) _Atomic int active;
    _Atomic int topo_entering;
    _Atomic int topology;
    _Atomic int drains;
    _Atomic int unwinds;
} __btrc_arc_stripe;

typedef struct __btrc_arc_pad_lock {
    _Alignas(128) _Atomic int word;
} __btrc_arc_pad_lock;

typedef struct __btrc_arc_shared_locks {
    __btrc_arc_stripe stripes[__BTRC_ARC_STRIPE_COUNT];
    __btrc_arc_pad_lock slot_locks[__BTRC_ARC_SLOT_LOCK_STRIPES];
    _Alignas(128) _Atomic int suspect_lock;
    _Atomic unsigned int next_stripe;
} __btrc_arc_shared_locks;

static _Atomic int __btrc_arc_lock_word = 0;
static __btrc_arc_shared_locks __btrc_arc_shared;

static inline void __btrc_arc_lock_relax(void) {
#if defined(__aarch64__) || defined(__arm__)
    __asm__ __volatile__("yield" ::: "memory");
#elif (defined(__x86_64__) || defined(__i386__)) && (defined(__GNUC__) || defined(__clang__))
    __asm__ __volatile__("pause" ::: "memory");
#endif
}

static inline void __btrc_arc_spin_lock(_Atomic int* word) {
    for (;;) {
        if (!atomic_exchange_explicit(word, 1, memory_order_acquire))
            return;
        while (atomic_load_explicit(word, memory_order_relaxed))
            __btrc_arc_lock_relax();
    }
}

static inline void __btrc_arc_spin_unlock(_Atomic int* word) {
    atomic_store_explicit(word, 0, memory_order_release);
}

static void __btrc_arc_lock_raw(void) {
    __btrc_arc_spin_lock(&__btrc_arc_lock_word);
}

static void __btrc_arc_unlock_raw(void) {
    __btrc_arc_spin_unlock(&__btrc_arc_lock_word);
}

static inline size_t __btrc_arc_my_stripe(void) {
    int stripe = __btrc_tls.arc_stripe;
    if (stripe > 0) return (size_t)(stripe - 1);
    size_t assigned = (size_t)atomic_fetch_add_explicit(
        &__btrc_arc_shared.next_stripe, 1u, memory_order_relaxed)
        & (__BTRC_ARC_STRIPE_COUNT - 1);
    __btrc_tls.arc_stripe = (int)(assigned + 1);
    return assigned;
}

static inline void __btrc_arc_drain_all_mutators(void) {
    for (size_t i = 0; i < __BTRC_ARC_STRIPE_COUNT; i++) {
        while (atomic_load_explicit(
                &__btrc_arc_shared.stripes[i].active, memory_order_seq_cst) != 0)
            __btrc_arc_lock_relax();
    }
}

static inline int __btrc_arc_any_topology_active(void) {
    for (size_t i = 0; i < __BTRC_ARC_STRIPE_COUNT; i++) {
        while (atomic_load_explicit(
                &__btrc_arc_shared.stripes[i].topo_entering, memory_order_seq_cst) != 0)
            __btrc_arc_lock_relax();
        if (atomic_load_explicit(
                &__btrc_arc_shared.stripes[i].topology, memory_order_seq_cst) != 0)
            return 1;
    }
    return 0;
}

#define __btrc_arc_suspect_lock() \
    __btrc_arc_spin_lock(&__btrc_arc_shared.suspect_lock)
#define __btrc_arc_suspect_unlock() \
    __btrc_arc_spin_unlock(&__btrc_arc_shared.suspect_lock)
#define __btrc_arc_slot_stripe(ptr) \
    ((size_t)((((uintptr_t)(ptr) >> 4) ^ ((uintptr_t)(ptr) >> 13) \
        ^ ((uintptr_t)(ptr) >> 22)) & (__BTRC_ARC_SLOT_LOCK_STRIPES - 1)))
#define __btrc_arc_slot_lock(stripe) \
    __btrc_arc_spin_lock(&__btrc_arc_shared.slot_locks[(stripe)].word)
#define __btrc_arc_slot_unlock(stripe) \
    __btrc_arc_spin_unlock(&__btrc_arc_shared.slot_locks[(stripe)].word)
#define __btrc_arc_obj_lock(object) do { \
    _Atomic unsigned short* __btrc_pl = &__btrc_arc_header_of(object)->pin_lock; \
    for (;;) { \
        if (!(atomic_fetch_or_explicit( \
                __btrc_pl, __BTRC_ARC_OBJ_LOCK_BIT, memory_order_acquire) \
                & __BTRC_ARC_OBJ_LOCK_BIT)) \
            break; \
        while (atomic_load_explicit(__btrc_pl, memory_order_relaxed) \
                & __BTRC_ARC_OBJ_LOCK_BIT) \
            __btrc_arc_lock_relax(); \
    } \
} while (0)
#define __btrc_arc_obj_unlock(object) \
    ((void)atomic_fetch_and_explicit( \
        &__btrc_arc_header_of(object)->pin_lock, \
        __BTRC_ARC_PIN_MASK, memory_order_release))
#define __btrc_arc_lock_objs(a, b, c, out, count_out) do { \
    void* __btrc_raw[3]; \
    int __btrc_n = 0; \
    if ((a)) __btrc_raw[__btrc_n++] = (a); \
    if ((b)) __btrc_raw[__btrc_n++] = (b); \
    if ((c)) __btrc_raw[__btrc_n++] = (c); \
    for (int __btrc_i = 1; __btrc_i < __btrc_n; __btrc_i++) { \
        void* __btrc_key = __btrc_raw[__btrc_i]; \
        int __btrc_j = __btrc_i - 1; \
        while (__btrc_j >= 0 \
                && (uintptr_t)__btrc_raw[__btrc_j] > (uintptr_t)__btrc_key) { \
            __btrc_raw[__btrc_j + 1] = __btrc_raw[__btrc_j]; \
            __btrc_j--; \
        } \
        __btrc_raw[__btrc_j + 1] = __btrc_key; \
    } \
    int __btrc_cnt = 0; \
    for (int __btrc_i = 0; __btrc_i < __btrc_n; __btrc_i++) { \
        if (__btrc_cnt == 0 || __btrc_raw[__btrc_i] != (out)[__btrc_cnt - 1]) { \
            (out)[__btrc_cnt] = __btrc_raw[__btrc_i]; \
            __btrc_arc_obj_lock((out)[__btrc_cnt]); \
            __btrc_cnt++; \
        } \
    } \
    (count_out) = __btrc_cnt; \
} while (0)
#define __btrc_arc_unlock_objs(objs, count) do { \
    for (int __btrc_i = (count) - 1; __btrc_i >= 0; __btrc_i--) \
        __btrc_arc_obj_unlock((objs)[__btrc_i]); \
} while (0)
/* btrc-runtime-helper:end __btrc_arc_lock_state */
/* btrc-runtime-helper:begin __btrc_arc_shutdown_state */
static _Atomic int __btrc_arc_shutdown = 0;
/* btrc-runtime-helper:end __btrc_arc_shutdown_state */
/* btrc-runtime-helper:begin __btrc_arc_active_drains_state */
/* Per-stripe drain counts live in __btrc_arc_shared.stripes[i].drains. */
/* btrc-runtime-helper:end __btrc_arc_active_drains_state */
/* btrc-runtime-helper:begin __btrc_arc_active_unwinds_state */
/* Per-stripe unwind counts live in __btrc_arc_shared.stripes[i].unwinds. */
/* btrc-runtime-helper:end __btrc_arc_active_unwinds_state */
/* btrc-runtime-helper:begin __btrc_arc_snapshot_state */
static _Atomic int __btrc_arc_snapshotting = 0;
/* btrc-runtime-helper:end __btrc_arc_snapshot_state */
/* btrc-runtime-helper:begin __btrc_arc_mutation_lock */
static inline void __btrc_arc_mutator_enter(size_t stripe) {
    if (__btrc_tls.arc_topology_depth > 0) return;
    for (;;) {
        if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_relaxed)) {
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        atomic_fetch_add_explicit(
            &__btrc_arc_shared.stripes[stripe].active, 1, memory_order_seq_cst);
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_seq_cst))
            return;
        atomic_fetch_sub_explicit(
            &__btrc_arc_shared.stripes[stripe].active, 1, memory_order_release);
        while (atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire))
            __btrc_arc_lock_relax();
    }
}

static inline void __btrc_arc_mutator_leave(size_t stripe) {
    if (__btrc_tls.arc_topology_depth > 0) return;
    atomic_fetch_sub_explicit(
        &__btrc_arc_shared.stripes[stripe].active, 1, memory_order_release);
}
/* btrc-runtime-helper:end __btrc_arc_mutation_lock */
/* btrc-runtime-helper:begin __btrc_arc_topology_state */
static _Atomic int __btrc_arc_topology_active = 0;
static _Atomic int __btrc_arc_topology_flush_pending = 0;
/* btrc-runtime-helper:end __btrc_arc_topology_state */
/* btrc-runtime-helper:begin __btrc_arc_topology_depth_state */
/* __btrc_tls.arc_topology_depth and __btrc_tls.arc_draining live in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_arc_topology_depth_state */
/* btrc-runtime-helper:begin __btrc_arc_topology_begin */
static void* __btrc_arc_topology_begin(void) {
    if (__btrc_tls.arc_topology_depth > 0) {
        if (__btrc_tls.arc_topology_depth == INT_MAX) {
            fprintf(stderr, "btrc: ARC topology scope overflow\n");
            exit(1);
        }
        __btrc_tls.arc_topology_depth++;
        return (void*)&__btrc_arc_topology_active;
    }
    size_t stripe = __btrc_arc_my_stripe();
    for (;;) {
        if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        while (atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)
                || (atomic_load_explicit(
                    &__btrc_arc_topology_flush_pending, memory_order_acquire)
                    && !__btrc_tls.arc_draining)) {
            if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
                fprintf(stderr, "btrc: ARC operation after shutdown\n");
                exit(1);
            }
            __btrc_arc_lock_relax();
        }
        atomic_fetch_add_explicit(
            &__btrc_arc_shared.stripes[stripe].topo_entering, 1, memory_order_seq_cst);
        if (!atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_seq_cst)
                && !atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_seq_cst)
                && (!atomic_load_explicit(
                    &__btrc_arc_topology_flush_pending, memory_order_seq_cst)
                    || __btrc_tls.arc_draining)) {
            atomic_fetch_add_explicit(
                &__btrc_arc_shared.stripes[stripe].topology, 1, memory_order_seq_cst);
            atomic_fetch_sub_explicit(
                &__btrc_arc_shared.stripes[stripe].topo_entering, 1, memory_order_release);
            __btrc_tls.arc_topology_depth = 1;
            return (void*)&__btrc_arc_topology_active;
        }
        atomic_fetch_sub_explicit(
            &__btrc_arc_shared.stripes[stripe].topo_entering, 1, memory_order_release);
    }
}
/* btrc-runtime-helper:end __btrc_arc_topology_begin */
/* btrc-runtime-helper:begin __btrc_arc_topology_leave */
static int __btrc_arc_topology_leave(void* token) {
    if (!token) return 0;
    if (token != (void*)&__btrc_arc_topology_active
            || __btrc_tls.arc_topology_depth <= 0) {
        fprintf(stderr, "btrc: invalid ARC topology scope\n");
        exit(1);
    }
    __btrc_tls.arc_topology_depth--;
    if (__btrc_tls.arc_topology_depth > 0) return 0;
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    size_t stripe = __btrc_arc_my_stripe();
    if (atomic_fetch_sub_explicit(
            &__btrc_arc_shared.stripes[stripe].topology, 1, memory_order_seq_cst) <= 0) {
        fprintf(stderr, "btrc: invalid ARC topology scope\n");
        exit(1);
    }
    if (!atomic_load_explicit(
            &__btrc_arc_topology_flush_pending, memory_order_seq_cst))
        return 0;
    return !__btrc_arc_any_topology_active();
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
/* __btrc_tls.arc_deferred_head and __btrc_tls.arc_deferred_tail live in the thread-local record __btrc_tls. */

static _Noreturn void __btrc_arc_raise_unlocked(
        const __btrc_arc_type* type, const char* message) {
    if (type && type->raise) type->raise(message);
    fprintf(stderr, "Unhandled exception: %s\n", message);
    exit(1);
}

static void __btrc_arc_enqueue_locked(void* object) {
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE
            || atomic_load_explicit(&header->rc, memory_order_acquire) != 0
            || atomic_load_explicit(&header->edge_rc, memory_order_acquire) != 0
            || header->incoming != NULL || header->deferred_next != NULL) {
        fprintf(stderr, "btrc: invalid ARC enqueue\n");
        exit(1);
    }
    atomic_store_explicit(&header->live_witness, NULL, memory_order_relaxed);
    atomic_store_explicit(&header->state, __BTRC_ARC_QUEUED, memory_order_release);
    if (__btrc_tls.arc_deferred_tail) {
        __btrc_arc_header_of(__btrc_tls.arc_deferred_tail)->deferred_next = object;
    } else {
        __btrc_tls.arc_deferred_head = object;
    }
    __btrc_tls.arc_deferred_tail = object;
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
        if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (__btrc_tls.arc_topology_depth != 0) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC snapshot inside topology mutation\n");
            exit(1);
        }
        if (!atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                && !atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {
            atomic_store_explicit(
                &__btrc_arc_snapshot_pending, 1, memory_order_seq_cst);
            __btrc_arc_unlock_raw();
            break;
        }
        __btrc_arc_unlock_raw();
        while (atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire))
            __btrc_arc_lock_relax();
    }
    for (;;) {
        if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (!__btrc_arc_any_topology_active()) {
            __btrc_arc_lock_raw();
            if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
                __btrc_arc_unlock_raw();
                fprintf(stderr, "btrc: ARC operation after shutdown\n");
                exit(1);
            }
            if (!__btrc_arc_any_topology_active()) {
                atomic_store_explicit(
                    &__btrc_arc_snapshotting, 1, memory_order_seq_cst);
                atomic_store_explicit(
                    &__btrc_arc_snapshot_pending, 0, memory_order_release);
                __btrc_arc_unlock_raw();
                __btrc_arc_drain_all_mutators();
                return;
            }
            __btrc_arc_unlock_raw();
        }
        __btrc_arc_lock_relax();
    }
}

static void __btrc_arc_exclusive_snapshot_end(void) {
    __btrc_arc_lock_raw();
    if (!atomic_load_explicit(
            &__btrc_arc_snapshotting, memory_order_acquire)) {
        __btrc_arc_unlock_raw();
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
static _Atomic int __btrc_reverse_count = 0;
static unsigned int __btrc_reverse_epoch = 0;
/* btrc-runtime-helper:end __btrc_arc_reverse_state */
/* btrc-runtime-helper:begin __btrc_arc_register_incoming */
static void __btrc_arc_register_incoming(
        void* object, void* owner) {
    if (!owner) {
        fprintf(stderr, "btrc: managed edge requires an owner\n");
        exit(1);
    }
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (!header->type || !header->type->visit) return;
    __btrc_arc_incoming* incoming = (__btrc_arc_incoming*)
        __btrc_safe_realloc(NULL, sizeof(__btrc_arc_incoming));
    incoming->owner = owner;
    incoming->next = header->incoming;
    header->incoming = incoming;
    if (owner != object)
        atomic_store_explicit(
            &header->live_witness, owner, memory_order_release);
}
/* btrc-runtime-helper:end __btrc_arc_register_incoming */
/* btrc-runtime-helper:begin __btrc_arc_unregister_incoming */
static void __btrc_arc_unregister_incoming(
        void* object, void* owner) {
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (!owner) {
        atomic_store_explicit(&header->live_witness, NULL, memory_order_release);
        return;
    }
    if (!header->type || !header->type->visit) return;
    __btrc_arc_incoming** link = &header->incoming;
    while (*link && (*link)->owner != owner) link = &(*link)->next;
    if (!*link) {
        fprintf(stderr, "btrc: missing managed incoming edge\n");
        exit(1);
    }
    __btrc_arc_incoming* removed = *link;
    *link = removed->next;
    free(removed);
    void* witness = atomic_load_explicit(&header->live_witness, memory_order_relaxed);
    if (witness == object || witness == owner) {
        void* replacement = NULL;
        for (__btrc_arc_incoming* edge = header->incoming;
                edge; edge = edge->next) {
            if (edge->owner != object) {
                replacement = edge->owner;
                break;
            }
        }
        atomic_store_explicit(&header->live_witness, replacement, memory_order_release);
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
        __btrc_arc_validate_unlocked(owner);
        if (atomic_load_explicit(
                &__btrc_arc_header_of(owner)->state, memory_order_acquire)
                != __BTRC_ARC_DESTROYING)
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
static void __btrc_reverse_grow_keys(int count) {
    int cap = __btrc_reverse_next_capacity(
        __btrc_reverse_key_cap, "reverse ARC hash overflow");
    size_t key_bytes = __btrc_reverse_capacity_bytes(
        cap, sizeof(void*), "reverse ARC hash size overflow");
    size_t mark_bytes = __btrc_reverse_capacity_bytes(
        cap, sizeof(unsigned int), "reverse ARC hash size overflow");
    void** keys = (void**)__btrc_safe_calloc(1, key_bytes);
    unsigned int* marks = (unsigned int*)__btrc_safe_calloc(1, mark_bytes);
    for (int i = 0; i < count; i++) {
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
static int __btrc_reverse_add(void* object, int* count_ref) {
    if (!object) return 0;
    int count = *count_ref;
    if (count < 0 || count == INT_MAX) {
        fprintf(stderr, "btrc: reverse ARC count overflow\n");
        exit(1);
    }
    if (__btrc_reverse_key_cap == 0
            || count >= __btrc_reverse_key_cap / 2)
        __btrc_reverse_grow_keys(count);
    size_t slot = __btrc_ptr_hash(object)
        & ((size_t)__btrc_reverse_key_cap - 1);
    while (__btrc_reverse_marks[slot] == __btrc_reverse_epoch) {
        if (__btrc_reverse_keys[slot] == object) return 0;
        slot = (slot + 1) & ((size_t)__btrc_reverse_key_cap - 1);
    }
    __btrc_reverse_reserve_queue(count + 1);
    __btrc_reverse_marks[slot] = __btrc_reverse_epoch;
    __btrc_reverse_keys[slot] = object;
    __btrc_reverse_queue[count++] = object;
    *count_ref = count;
    atomic_store_explicit(&__btrc_reverse_count, count, memory_order_relaxed);
    return 1;
}
static int __btrc_arc_reverse_proves_live(void* object) {
    int count = 0;
    atomic_store_explicit(&__btrc_reverse_count, 0, memory_order_relaxed);
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
    void* preferred = object;
    while (preferred && __btrc_reverse_add(preferred, &count)) {
        __btrc_arc_validate(preferred);
        __btrc_arc_header* header = __btrc_arc_header_of(preferred);
        if (atomic_load_explicit(&header->rc, memory_order_acquire)
                > atomic_load_explicit(&header->edge_rc, memory_order_acquire))
            return 1;
        void* witness = atomic_load_explicit(&header->live_witness, memory_order_acquire);
        if (witness == preferred) break;
        preferred = witness;
    }
    for (int head = 0; head < count; head++) {
        void* current = __btrc_reverse_queue[head];
        __btrc_arc_validate(current);
        __btrc_arc_header* header = __btrc_arc_header_of(current);
        if (atomic_load_explicit(&header->rc, memory_order_acquire)
                > atomic_load_explicit(&header->edge_rc, memory_order_acquire))
            return 1;
        for (__btrc_arc_incoming* edge = header->incoming;
                edge; edge = edge->next)
            __btrc_reverse_add(edge->owner, &count);
    }
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_reverse_proves_live */
/* btrc-runtime-helper:begin __btrc_arc_retain */
static inline int __btrc_arc_retain(void* object) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_validate_unlocked(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* type = header->type;
    if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE) {
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            type, "cannot retain destroying managed object");
    }
    int prev = atomic_fetch_add_explicit(&header->rc, 1, memory_order_relaxed);
    if (prev == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    void* witness = atomic_load_explicit(&header->live_witness, memory_order_relaxed);
    if (witness == object) {
        atomic_compare_exchange_strong_explicit(
            &header->live_witness, &witness, NULL,
            memory_order_relaxed, memory_order_relaxed);
    }
    __btrc_arc_validate_unlocked(object);
    __btrc_arc_mutator_leave(stripe);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_retain */
/* btrc-runtime-helper:begin __btrc_arc_retain_edge */
static inline int __btrc_arc_retain_edge(
        void* object, void* owner) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->type && !header->type->visit) {
        __btrc_arc_validate_unlocked(object);
        if (owner) __btrc_arc_validate_unlocked(owner);
        const __btrc_arc_type* error_type = header->type;
        int obj_state = atomic_load_explicit(&header->state, memory_order_acquire);
        int owner_bad = owner && atomic_load_explicit(
            &__btrc_arc_header_of(owner)->state, memory_order_acquire) != __BTRC_ARC_LIVE;
        if (obj_state != __BTRC_ARC_LIVE || owner_bad) {
            if (owner_bad) error_type = __btrc_arc_header_of(owner)->type;
            __btrc_arc_mutator_leave(stripe);
            __btrc_arc_raise_unlocked(
                error_type, "cannot retain destroying managed object");
        }
        if (!owner) {
            fprintf(stderr, "btrc: managed edge requires an owner\n");
            exit(1);
        }
        int prev_rc = atomic_fetch_add_explicit(&header->rc, 1, memory_order_relaxed);
        if (prev_rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
        int prev_erc = atomic_fetch_add_explicit(&header->edge_rc, 1, memory_order_release);
        if (prev_erc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
        __btrc_arc_mutator_leave(stripe);
        return 0;
    }
    void* locks[3];
    int lock_count = 0;
    __btrc_arc_lock_objs(object, owner, NULL, locks, lock_count);
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    const __btrc_arc_type* error_type = header->type;
    int obj_state = atomic_load_explicit(&header->state, memory_order_acquire);
    int owner_bad = owner && atomic_load_explicit(
        &__btrc_arc_header_of(owner)->state, memory_order_acquire) != __BTRC_ARC_LIVE;
    if (obj_state != __BTRC_ARC_LIVE || owner_bad) {
        if (owner_bad) error_type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
    }
    int prev_rc = atomic_fetch_add_explicit(&header->rc, 1, memory_order_relaxed);
    if (prev_rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    int prev_erc = atomic_fetch_add_explicit(&header->edge_rc, 1, memory_order_release);
    if (prev_erc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    __btrc_arc_register_incoming(object, owner);
    __btrc_arc_validate(object);
    __btrc_arc_unlock_objs(locks, lock_count);
    __btrc_arc_mutator_leave(stripe);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_retain_edge */
/* btrc-runtime-helper:begin __btrc_arc_adopt_edge */
static inline int __btrc_arc_adopt_edge(
        void* object, void* owner) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    void* locks[3];
    int lock_count = 0;
    __btrc_arc_lock_objs(object, owner, NULL, locks, lock_count);
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* error_type = header->type;
    int obj_state = atomic_load_explicit(&header->state, memory_order_acquire);
    int owner_bad = owner && atomic_load_explicit(
        &__btrc_arc_header_of(owner)->state, memory_order_acquire) != __BTRC_ARC_LIVE;
    if (obj_state != __BTRC_ARC_LIVE || owner_bad) {
        if (owner_bad) error_type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
    }
    int cur_erc = atomic_load_explicit(&header->edge_rc, memory_order_relaxed);
    int cur_rc = atomic_load_explicit(&header->rc, memory_order_acquire);
    if (cur_erc == INT_MAX || cur_erc >= cur_rc) {
        fprintf(stderr, "btrc: invalid owned-edge adoption\n");
        exit(1);
    }
    __btrc_arc_register_incoming(object, owner);
    atomic_store_explicit(&header->edge_rc, cur_erc + 1, memory_order_release);
    __btrc_arc_validate(object);
    __btrc_arc_unlock_objs(locks, lock_count);
    __btrc_arc_mutator_leave(stripe);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_adopt_edge */
/* btrc-runtime-helper:begin __btrc_arc_unlink_edge */
static inline int __btrc_arc_unlink_edge(
        void* object, void* owner) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    void* locks[3];
    int lock_count = 0;
    __btrc_arc_lock_objs(object, owner, NULL, locks, lock_count);
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    int obj_state = atomic_load_explicit(&header->state, memory_order_acquire);
    int owner_state = owner
        ? atomic_load_explicit(&__btrc_arc_header_of(owner)->state, memory_order_acquire)
        : __BTRC_ARC_LIVE;
    if (obj_state != __BTRC_ARC_LIVE
            || (owner && owner_state != __BTRC_ARC_LIVE
                && owner_state != __BTRC_ARC_DESTROYING)) {
        const __btrc_arc_type* type = header->type;
        if (owner && owner_state != __BTRC_ARC_LIVE
                && owner_state != __BTRC_ARC_DESTROYING)
            type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            type, "cannot retain destroying managed object");
    }
    __btrc_arc_unregister_incoming(object, owner);
    __btrc_arc_unlock_objs(locks, lock_count);
    __btrc_arc_mutator_leave(stripe);
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
    int index = __btrc_suspect_slots[hole];
    __btrc_suspect_keys[hole] = NULL;
    size_t scan = (hole + 1) & mask;
    while (__btrc_suspect_keys[scan]) {
        void* displaced = __btrc_suspect_keys[scan];
        int displaced_index = __btrc_suspect_slots[scan];
        __btrc_suspect_keys[scan] = NULL;
        size_t target = __btrc_ptr_hash(displaced) & mask;
        while (__btrc_suspect_keys[target])
            target = (target + 1) & mask;
        __btrc_suspect_keys[target] = displaced;
        __btrc_suspect_slots[target] = displaced_index;
        scan = (scan + 1) & mask;
    }
    if (index < 0 || index >= __btrc_suspect_count
            || __btrc_suspects[index] != obj) {
        fprintf(stderr, "btrc: cycle suspect buffer out of sync\n");
        exit(1);
    }
    int last = --__btrc_suspect_count;
    atomic_store_explicit(
        &__btrc_arc_header_of(obj)->in_suspects, 0, memory_order_release);
    atomic_store_explicit(
        &__btrc_suspect_count_atomic, __btrc_suspect_count, memory_order_release);
    if (index == last) return;
    void* moved = __btrc_suspects[last];
    __btrc_suspects[index] = moved;
    __btrc_visit_table[index] = __btrc_visit_table[last];
    __btrc_destroy_table[index] = __btrc_destroy_table[last];
    size_t moved_slot = __btrc_ptr_hash(moved) & mask;
    while (__btrc_suspect_keys[moved_slot] != moved) {
        if (!__btrc_suspect_keys[moved_slot]) {
            fprintf(stderr, "btrc: cycle suspect hash lost a suspect\n");
            exit(1);
        }
        moved_slot = (moved_slot + 1) & mask;
    }
    __btrc_suspect_slots[moved_slot] = index;
}
/* btrc-runtime-helper:end __btrc_forget_suspect */
/* btrc-runtime-helper:begin __btrc_arc_release_impl */
static inline int __btrc_arc_lock_raw_trylock(void) {
    if (atomic_load_explicit(&__btrc_arc_lock_word, memory_order_relaxed))
        return 0;
    return !atomic_exchange_explicit(
        &__btrc_arc_lock_word, 1, memory_order_acquire);
}

static inline int __btrc_arc_obj_trylock(void* object) {
    _Atomic unsigned short* pl = &__btrc_arc_header_of(object)->pin_lock;
    if (atomic_load_explicit(pl, memory_order_relaxed) & __BTRC_ARC_OBJ_LOCK_BIT)
        return 0;
    return !(atomic_fetch_or_explicit(pl, __BTRC_ARC_OBJ_LOCK_BIT, memory_order_acquire)
        & __BTRC_ARC_OBJ_LOCK_BIT);
}

static void __btrc_arc_maybe_suspect_pinned(
        void* object, const __btrc_arc_type* type, size_t stripe) {
    __btrc_arc_header* root_hdr = __btrc_arc_header_of(object);
    int proved_live = 0;
    int contended = 0;
    int hops = 1;
    void* tortoise = object;
    int power = 1;
    int lam = 0;
    __btrc_arc_obj_lock(object);
    int root_state = atomic_load_explicit(&root_hdr->state, memory_order_acquire);
    int root_rc = atomic_load_explicit(&root_hdr->rc, memory_order_acquire);
    int root_erc = atomic_load_explicit(&root_hdr->edge_rc, memory_order_acquire);
    if (root_state != __BTRC_ARC_LIVE || root_rc == 0 || root_rc > root_erc
            || __btrc_arc_incoming_teardown_pending(object)) {
        atomic_fetch_sub_explicit(&root_hdr->pin_lock, 1u, memory_order_release);
        __btrc_arc_obj_unlock(object);
        return;
    }
    void* cur = object;
    while (hops < 2048) {
        void* next = atomic_load_explicit(
            &__btrc_arc_header_of(cur)->live_witness, memory_order_acquire);
        if (!next || next == cur || next == tortoise || next == object) break;
        int locked = __btrc_arc_obj_trylock(next);
        if (!locked) {
            for (int retry = 0; retry < 8 && !locked; retry++) {
                __btrc_arc_lock_relax();
                locked = __btrc_arc_obj_trylock(next);
            }
        }
        if (!locked) {
            contended = 1;
            break;
        }
        __btrc_arc_obj_unlock(cur);
        cur = next;
        hops++;
        __btrc_arc_header* next_hdr = __btrc_arc_header_of(next);
        if (atomic_load_explicit(&next_hdr->rc, memory_order_acquire)
                > atomic_load_explicit(&next_hdr->edge_rc, memory_order_acquire)) {
            proved_live = 1;
            break;
        }
        lam++;
        if (lam == power) {
            tortoise = next;
            power <<= 1;
            lam = 0;
        }
    }
    __btrc_arc_obj_unlock(cur);
    if (proved_live) {
        if (atomic_load_explicit(&__btrc_arc_shared.next_stripe, memory_order_relaxed) <= 1u)
            atomic_store_explicit(&__btrc_reverse_count, hops, memory_order_relaxed);
        atomic_fetch_sub_explicit(&root_hdr->pin_lock, 1u, memory_order_release);
        return;
    }
    if (!contended && __btrc_tls.arc_topology_depth == 0) {
        __btrc_arc_mutator_leave(stripe);
        int froze = 0;
        if (__btrc_arc_lock_raw_trylock()) {
            if (!atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)
                    && !atomic_load_explicit(&__btrc_arc_snapshotting, memory_order_acquire)
                    && !atomic_load_explicit(&__btrc_arc_snapshot_pending, memory_order_acquire)) {
                atomic_store_explicit(&__btrc_arc_snapshotting, 1, memory_order_seq_cst);
                if (!__btrc_arc_any_topology_active()) {
                    __btrc_arc_unlock_raw();
                    __btrc_arc_drain_all_mutators();
                    froze = 1;
                } else {
                    atomic_store_explicit(&__btrc_arc_snapshotting, 0, memory_order_release);
                    __btrc_arc_unlock_raw();
                }
            } else {
                __btrc_arc_unlock_raw();
            }
        }
        if (froze) {
            int st = atomic_load_explicit(&root_hdr->state, memory_order_acquire);
            int r = atomic_load_explicit(&root_hdr->rc, memory_order_acquire);
            int e = atomic_load_explicit(&root_hdr->edge_rc, memory_order_acquire);
            if (st == __BTRC_ARC_LIVE && r > 0 && r == e
                    && !__btrc_arc_incoming_teardown_pending(object)
                    && !__btrc_arc_reverse_proves_live(object)) {
                __btrc_suspect_locked(object, type->visit, type->destroy);
            }
            atomic_fetch_sub_explicit(&root_hdr->pin_lock, 1u, memory_order_release);
            __btrc_arc_lock_raw();
            atomic_store_explicit(&__btrc_arc_snapshotting, 0, memory_order_release);
            __btrc_arc_unlock_raw();
            __btrc_arc_mutator_enter(stripe);
            return;
        }
        __btrc_arc_mutator_enter(stripe);
    }
    __btrc_arc_obj_lock(object);
    int st = atomic_load_explicit(&root_hdr->state, memory_order_acquire);
    int r = atomic_load_explicit(&root_hdr->rc, memory_order_acquire);
    int e = atomic_load_explicit(&root_hdr->edge_rc, memory_order_acquire);
    if (st == __BTRC_ARC_LIVE && r > 0 && r == e
            && !__btrc_arc_incoming_teardown_pending(object)) {
        __btrc_arc_suspect_lock();
        __btrc_suspect_locked(object, type->visit, type->destroy);
        __btrc_arc_suspect_unlock();
        if (__btrc_tls.arc_topology_depth > 0
                && atomic_load_explicit(
                    &__btrc_suspect_count_atomic, memory_order_acquire) > 0) {
            atomic_store_explicit(
                &__btrc_arc_topology_flush_pending, 1, memory_order_release);
        }
    }
    atomic_fetch_sub_explicit(&root_hdr->pin_lock, 1u, memory_order_release);
    __btrc_arc_obj_unlock(object);
}

static inline int __btrc_arc_release_locked_obj(
        void* object, const __btrc_arc_type* fallback,
        int edge, const __btrc_arc_type** out_suspect_type) {
    *out_suspect_type = NULL;
    if (!object) return 0;
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy) { fprintf(stderr, "btrc: untyped managed release\n"); exit(1); }
    if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE) {
        fprintf(stderr, "btrc: release of non-live managed object\n");
        exit(1);
    }
    int cur_erc = atomic_load_explicit(&header->edge_rc, memory_order_relaxed);
    if (edge) {
        if (cur_erc <= 0) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
        cur_erc--;
        atomic_store_explicit(&header->edge_rc, cur_erc, memory_order_release);
    }
    int prev_rc = atomic_fetch_sub_explicit(&header->rc, 1, memory_order_acq_rel);
    if (prev_rc <= 0) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
    int new_rc = prev_rc - 1;
    if (new_rc == 0) {
        if (cur_erc != 0 || header->incoming != NULL) {
            fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
            exit(1);
        }
        if (atomic_load_explicit(&header->in_suspects, memory_order_acquire)) {
            __btrc_arc_suspect_lock();
            __btrc_forget_suspect(object);
            __btrc_arc_suspect_unlock();
        }
        __btrc_arc_enqueue_locked(object);
        return 0;
    }
    __btrc_arc_validate(object);
    if (type->visit && new_rc == cur_erc
            && !__btrc_arc_incoming_teardown_pending(object)) {
        atomic_fetch_add_explicit(&header->pin_lock, 1u, memory_order_acq_rel);
        *out_suspect_type = type;
    }
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
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    size_t slot_s = __btrc_arc_slot_stripe((const void*)slot_storage);
    __btrc_arc_slot_lock(slot_s);
    void* object = access(slot_storage, NULL, NULL, 0);
    void* locks[3];
    int lock_count = 0;
    __btrc_arc_lock_objs(owner, object, replacement, locks, lock_count);
    __btrc_arc_validate(owner);
    __btrc_arc_header* owner_header = __btrc_arc_header_of(owner);
    const __btrc_arc_type* error_type = owner_header->type;
    int owner_state = atomic_load_explicit(&owner_header->state, memory_order_acquire);
    int invalid_publication = replacement && owner_state != __BTRC_ARC_LIVE;
    if (replacement) {
        __btrc_arc_validate(replacement);
        if (atomic_load_explicit(
                &__btrc_arc_header_of(replacement)->state, memory_order_acquire)
                != __BTRC_ARC_LIVE) {
            invalid_publication = 1;
            error_type = __btrc_arc_header_of(replacement)->type;
        }
    }
    if (invalid_publication) {
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
        return -1;
    }
    if (!replacement && owner_state != __BTRC_ARC_LIVE
            && owner_state != __BTRC_ARC_DESTROYING) {
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
        return -1;
    }
    const __btrc_arc_type* suspect_type = NULL;
    void* suspect_obj = NULL;
    if (object == replacement) {
        if (replacement && adopt) {
            __btrc_arc_release_locked_obj(replacement, fallback, 0, &suspect_type);
            if (suspect_type) suspect_obj = replacement;
        }
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_slot_unlock(slot_s);
        if (suspect_obj)
            __btrc_arc_maybe_suspect_pinned(suspect_obj, suspect_type, stripe);
        __btrc_arc_mutator_leave(stripe);
        if (__btrc_tls.arc_deferred_head) __btrc_arc_drain_deferred(0);
        return 0;
    }
    if (access(slot_storage, object, replacement, 1) != object) {
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
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
            int cur_erc = atomic_load_explicit(&next->edge_rc, memory_order_relaxed);
            int cur_rc = atomic_load_explicit(&next->rc, memory_order_acquire);
            if (cur_erc == INT_MAX || cur_erc >= cur_rc) {
                fprintf(stderr, "btrc: invalid owned-edge adoption\n");
                exit(1);
            }
            __btrc_arc_register_incoming(replacement, owner);
            atomic_store_explicit(&next->edge_rc, cur_erc + 1, memory_order_release);
        } else {
            int prev_rc = atomic_fetch_add_explicit(&next->rc, 1, memory_order_relaxed);
            if (prev_rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
            int prev_erc = atomic_fetch_add_explicit(&next->edge_rc, 1, memory_order_release);
            if (prev_erc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
            __btrc_arc_register_incoming(replacement, owner);
        }
        __btrc_arc_validate(replacement);
    }
    if (object) {
        __btrc_arc_release_locked_obj(object, fallback, 1, &suspect_type);
        if (suspect_type) suspect_obj = object;
    }
    __btrc_arc_unlock_objs(locks, lock_count);
    __btrc_arc_slot_unlock(slot_s);
    if (suspect_obj)
        __btrc_arc_maybe_suspect_pinned(suspect_obj, suspect_type, stripe);
    __btrc_arc_mutator_leave(stripe);
    if (__btrc_tls.arc_deferred_head) __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_replace_edge */
/* btrc-runtime-helper:begin __btrc_arc_release */
static inline int __btrc_arc_release(
        void* object, const __btrc_arc_type* type) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* runtime_type = __btrc_arc_type_of(object, type);
    if (!runtime_type || !runtime_type->destroy) {
        fprintf(stderr, "btrc: untyped managed release\n");
        exit(1);
    }
    if (!runtime_type->visit) {
        __btrc_arc_validate_unlocked(object);
        if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE) {
            fprintf(stderr, "btrc: release of non-live managed object\n");
            exit(1);
        }
        int prev_rc = atomic_fetch_sub_explicit(&header->rc, 1, memory_order_acq_rel);
        if (prev_rc <= 0) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
        if (prev_rc == 1) {
            if (atomic_load_explicit(&header->edge_rc, memory_order_acquire) != 0
                    || header->incoming != NULL) {
                fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
                exit(1);
            }
            if (atomic_load_explicit(&header->in_suspects, memory_order_acquire)) {
                __btrc_arc_suspect_lock();
                __btrc_forget_suspect(object);
                __btrc_arc_suspect_unlock();
            }
            __btrc_arc_enqueue_locked(object);
        }
        __btrc_arc_mutator_leave(stripe);
        if (__btrc_tls.arc_deferred_head) __btrc_arc_drain_deferred(0);
        return 0;
    }
    __btrc_arc_obj_lock(object);
    const __btrc_arc_type* suspect_type = NULL;
    __btrc_arc_release_locked_obj(object, type, 0, &suspect_type);
    __btrc_arc_obj_unlock(object);
    if (suspect_type)
        __btrc_arc_maybe_suspect_pinned(object, suspect_type, stripe);
    __btrc_arc_mutator_leave(stripe);
    if (__btrc_tls.arc_deferred_head) __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release */
/* btrc-runtime-helper:begin __btrc_arc_release_edge */
static inline int __btrc_arc_release_edge(
        void* object, const __btrc_arc_type* type, void* replacement) {
    (void)replacement;
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_obj_lock(object);
    const __btrc_arc_type* suspect_type = NULL;
    __btrc_arc_release_locked_obj(object, type, 1, &suspect_type);
    __btrc_arc_obj_unlock(object);
    if (suspect_type)
        __btrc_arc_maybe_suspect_pinned(object, suspect_type, stripe);
    __btrc_arc_mutator_leave(stripe);
    if (__btrc_tls.arc_deferred_head) __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release_edge */
/* btrc-runtime-helper:begin __btrc_arc_release_acyclic */
static inline int __btrc_arc_release_acyclic(
        void* object, const __btrc_arc_type* type) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_validate_unlocked(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* runtime_type = __btrc_arc_type_of(object, type);
    if (!runtime_type || !runtime_type->destroy) { fprintf(stderr, "btrc: untyped managed release\n"); exit(1); }
    if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE) {
        fprintf(stderr, "btrc: reference count underflow\n");
        exit(1);
    }
    int prev_rc = atomic_fetch_sub_explicit(&header->rc, 1, memory_order_acq_rel);
    if (prev_rc <= 0) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
    if (prev_rc == 1) {
        if (atomic_load_explicit(&header->edge_rc, memory_order_acquire) != 0
                || header->incoming != NULL) {
            fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
            exit(1);
        }
        __btrc_arc_enqueue_locked(object);
    }
    __btrc_arc_mutator_leave(stripe);
    if (__btrc_tls.arc_deferred_head) __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_release_acyclic */
/* btrc-runtime-helper:begin __btrc_arc_invalidate */
static inline int __btrc_arc_invalidate(void* object) {
    if (!object) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_obj_lock(object);
    __btrc_arc_validate(object);
    __btrc_arc_obj_unlock(object);
    __btrc_arc_mutator_leave(stripe);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_invalidate */
/* btrc-runtime-helper:begin __btrc_arc_destroy_slot */
static inline int __btrc_arc_destroy_slot(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access,
        const __btrc_arc_type* fallback) {
    if (!slot_storage || !access) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    size_t slot_s = __btrc_arc_slot_stripe((const void*)slot_storage);
    __btrc_arc_slot_lock(slot_s);
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) {
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        return 0;
    }
    __btrc_arc_obj_lock(object);
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy) { fprintf(stderr, "btrc: untyped managed destroy\n"); exit(1); }
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE
            || atomic_load_explicit(&header->rc, memory_order_acquire) != 1
            || atomic_load_explicit(&header->edge_rc, memory_order_acquire) != 0
            || header->incoming != NULL) {
        __btrc_arc_obj_unlock(object);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            type, "cannot delete shared managed object");
    }
    if (access(slot_storage, object, NULL, 1) != object) {
        __btrc_arc_obj_unlock(object);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        fprintf(stderr, "btrc: managed delete slot changed during transaction\n");
        exit(1);
    }
    atomic_store_explicit(&header->rc, 0, memory_order_release);
    atomic_store_explicit(&header->live_witness, NULL, memory_order_relaxed);
    if (atomic_load_explicit(&header->in_suspects, memory_order_acquire)) {
        __btrc_arc_suspect_lock();
        __btrc_forget_suspect(object);
        __btrc_arc_suspect_unlock();
    }
    __btrc_arc_enqueue_locked(object);
    __btrc_arc_obj_unlock(object);
    __btrc_arc_slot_unlock(slot_s);
    __btrc_arc_mutator_leave(stripe);
    __btrc_arc_drain_deferred(0);
    return 0;
}
/* btrc-runtime-helper:end __btrc_arc_destroy_slot */
/* btrc-runtime-helper:begin __btrc_arc_destroy_edge */
static inline int __btrc_arc_destroy_edge(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access, void* owner,
        const __btrc_arc_type* fallback) {
    if (!slot_storage || !access || !owner) return 0;
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    size_t slot_s = __btrc_arc_slot_stripe((const void*)slot_storage);
    __btrc_arc_slot_lock(slot_s);
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) {
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        return 0;
    }
    void* locks[3];
    int lock_count = 0;
    __btrc_arc_lock_objs(owner, object, NULL, locks, lock_count);
    __btrc_arc_validate(owner);
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    __btrc_arc_header* owner_header = __btrc_arc_header_of(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    int owner_state = atomic_load_explicit(&owner_header->state, memory_order_acquire);
    int owner_valid = owner_state == __BTRC_ARC_LIVE
        || owner_state == __BTRC_ARC_DESTROYING;
    int incoming_unique = (header->type && header->type->visit)
        ? (header->incoming && header->incoming->owner == owner
            && header->incoming->next == NULL)
        : (header->incoming == NULL);
    int unique = atomic_load_explicit(&header->state, memory_order_acquire) == __BTRC_ARC_LIVE
        && atomic_load_explicit(&header->rc, memory_order_acquire) == 1
        && atomic_load_explicit(&header->edge_rc, memory_order_acquire) == 1
        && incoming_unique;
    if (!owner_valid || !unique) {
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        __btrc_arc_raise_unlocked(
            type, "cannot delete shared managed object");
    }
    if (access(slot_storage, object, NULL, 1) != object) {
        __btrc_arc_unlock_objs(locks, lock_count);
        __btrc_arc_slot_unlock(slot_s);
        __btrc_arc_mutator_leave(stripe);
        fprintf(stderr, "btrc: managed delete slot changed during transaction\n");
        exit(1);
    }
    __btrc_arc_unregister_incoming(object, owner);
    atomic_store_explicit(&header->edge_rc, 0, memory_order_release);
    atomic_store_explicit(&header->rc, 0, memory_order_release);
    atomic_store_explicit(&header->live_witness, NULL, memory_order_relaxed);
    if (atomic_load_explicit(&header->in_suspects, memory_order_acquire)) {
        __btrc_arc_suspect_lock();
        __btrc_forget_suspect(object);
        __btrc_arc_suspect_unlock();
    }
    __btrc_arc_enqueue_locked(object);
    __btrc_arc_unlock_objs(locks, lock_count);
    __btrc_arc_slot_unlock(slot_s);
    __btrc_arc_mutator_leave(stripe);
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
        int hdr_state = atomic_load_explicit(&header->state, memory_order_acquire);
        int hdr_rc = atomic_load_explicit(&header->rc, memory_order_acquire);
        int hdr_erc = atomic_load_explicit(&header->edge_rc, memory_order_acquire);
        int incoming_ok = (header->type && header->type->visit)
            ? (incoming == hdr_erc)
            : (incoming == 0);
        if (hdr_state != __BTRC_ARC_LIVE
                || !incoming_ok
                || hdr_rc < owned
                || hdr_erc < vertex->internal)
            __btrc_cycle_fail("invalid escaping partial construction");
        if (vertex->root && hdr_erc != vertex->internal)
            __btrc_cycle_fail("invalid escaping partial construction");
        if (hdr_rc > owned) {
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
        int cur_rc = atomic_load_explicit(&header->rc, memory_order_acquire);
        int cur_erc = atomic_load_explicit(&header->edge_rc, memory_order_acquire);
        if (cur_rc <= 0 || cur_erc <= 0)
            __btrc_cycle_fail("partial-construction edge underflow");
        atomic_store_explicit(&header->edge_rc, cur_erc - 1, memory_order_release);
        atomic_store_explicit(&header->rc, cur_rc - 1, memory_order_release);
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        if (!vertex->root) continue;
        __btrc_arc_header* root =
            __btrc_arc_header_of(vertex->object);
        int cur_rc = atomic_load_explicit(&root->rc, memory_order_acquire);
        if (cur_rc <= 0)
            __btrc_cycle_fail("partial-construction root underflow");
        atomic_store_explicit(&root->rc, cur_rc - 1, memory_order_release);
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        __btrc_arc_header* header =
            __btrc_arc_header_of(vertex->object);
        if (vertex->live) {
            __btrc_arc_validate(vertex->object);
            continue;
        }
        if (atomic_load_explicit(&header->rc, memory_order_acquire) != 0
                || atomic_load_explicit(&header->edge_rc, memory_order_acquire) != 0
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
/* __btrc_tls.abandon_drain_callback lives in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_arc_abandon_callback_state */
/* btrc-runtime-helper:begin __btrc_arc_abandon_queue_state */
/* __btrc_tls.abandon_queue, __btrc_tls.abandon_count and __btrc_tls.abandon_cap live in the thread-local record __btrc_tls. */
/* btrc-runtime-helper:end __btrc_arc_abandon_queue_state */
/* btrc-runtime-helper:begin __btrc_arc_abandon_queue_drain */
static void __btrc_arc_drain_pending_abandons(void) {
    __btrc_abandon_drain_fn callback =
        __btrc_tls.abandon_drain_callback;
    if (callback) callback();
}
/* btrc-runtime-helper:end __btrc_arc_abandon_queue_drain */
/* btrc-runtime-helper:begin __btrc_arc_abandon */
static void __btrc_arc_drain_abandon_queue(void) {
    if (__btrc_tls.arc_topology_depth != 0) return;
    for (;;) {
        if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        void** batch = __btrc_tls.abandon_queue;
        int count = __btrc_tls.abandon_count;
        __btrc_tls.abandon_queue = NULL;
        __btrc_tls.abandon_count = 0;
        __btrc_tls.abandon_cap = 0;
        __btrc_tls.abandon_drain_callback = NULL;
        if (count == 0) {
            free(batch);
            break;
        }
        __btrc_arc_abandon_many(batch, count, 1);
    }
}

static void __btrc_arc_abandon(void* object) {
    if (!object) return;
    if (__btrc_tls.arc_topology_depth == 0) {
        __btrc_arc_abandon_now(object);
        return;
    }
    size_t stripe = __btrc_arc_my_stripe();
    __btrc_arc_mutator_enter(stripe);
    __btrc_arc_validate_unlocked(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_LIVE) {
        __btrc_arc_mutator_leave(stripe);
        fprintf(stderr, "btrc: invalid deferred construction abandon\n");
        exit(1);
    }
    if (__btrc_tls.abandon_count < 0 || __btrc_tls.abandon_cap < 0
            || __btrc_tls.abandon_count > __btrc_tls.abandon_cap) {
        __btrc_arc_mutator_leave(stripe);
        fprintf(stderr, "btrc: invalid construction abandon capacity\n");
        exit(1);
    }
    for (int i = 0; i < __btrc_tls.abandon_count; i++) {
        if (__btrc_tls.abandon_queue[i] == object) {
            __btrc_arc_mutator_leave(stripe);
            fprintf(stderr, "btrc: duplicate deferred construction abandon\n");
            exit(1);
        }
    }
    if (__btrc_tls.abandon_count == INT_MAX) {
        __btrc_arc_mutator_leave(stripe);
        fprintf(stderr, "btrc: construction abandon queue overflow\n");
        exit(1);
    }
    if (__btrc_tls.abandon_count >= __btrc_tls.abandon_cap) {
        if (__btrc_tls.abandon_cap > INT_MAX / 2) {
            __btrc_arc_mutator_leave(stripe);
            fprintf(stderr, "btrc: construction abandon capacity overflow\n");
            exit(1);
        }
        int cap = __btrc_tls.abandon_cap
            ? __btrc_tls.abandon_cap * 2 : 16;
        if ((size_t)cap > SIZE_MAX / sizeof(void*)) {
            __btrc_arc_mutator_leave(stripe);
            fprintf(stderr, "btrc: construction abandon size overflow\n");
            exit(1);
        }
        size_t bytes = sizeof(void*) * (size_t)cap;
        __btrc_tls.abandon_queue = (void**)__btrc_safe_realloc(
            __btrc_tls.abandon_queue, bytes);
        __btrc_tls.abandon_cap = cap;
    }
    __btrc_tls.abandon_queue[__btrc_tls.abandon_count++] = object;
    __btrc_tls.abandon_drain_callback =
        __btrc_arc_drain_abandon_queue;
    atomic_store_explicit(&__btrc_arc_topology_flush_pending, 1, memory_order_release);
    __btrc_arc_mutator_leave(stripe);
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
        if (atomic_load_explicit(&header->rc, memory_order_acquire)
                > atomic_load_explicit(&header->edge_rc, memory_order_acquire)) {
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
        __btrc_arc_header* header = __btrc_arc_header_of(object);
        atomic_store_explicit(&header->in_suspects, 0, memory_order_release);
        __btrc_arc_validate(object);
        if (atomic_load_explicit(&header->rc, memory_order_acquire)
                > atomic_load_explicit(&header->edge_rc, memory_order_acquire))
            continue;
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
    atomic_store_explicit(&__btrc_suspect_count_atomic, 0, memory_order_release);
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
        if (atomic_load_explicit(&header->rc, memory_order_acquire)
                > atomic_load_explicit(&header->edge_rc, memory_order_acquire)) {
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
        int rc = atomic_load_explicit(
            &__btrc_arc_header_of(vertex->object)->rc, memory_order_acquire);
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
            atomic_store_explicit(&header->live_witness, NULL, memory_order_release);
        } else if (atomic_load_explicit(&header->rc, memory_order_acquire)
                == atomic_load_explicit(&header->edge_rc, memory_order_acquire)
                && !atomic_load_explicit(&header->live_witness, memory_order_acquire)) {
            atomic_store_explicit(&header->live_witness, vertex->object, memory_order_release);
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
        int cur_rc = atomic_load_explicit(&target->rc, memory_order_acquire);
        int cur_erc = atomic_load_explicit(&target->edge_rc, memory_order_acquire);
        if (cur_rc <= 0 || cur_erc <= 0)
            __btrc_cycle_fail("managed edge count underflow");
        atomic_store_explicit(&target->edge_rc, cur_erc - 1, memory_order_release);
        atomic_store_explicit(&target->rc, cur_rc - 1, memory_order_release);
        if (cur_rc - 1 > 0)
            __btrc_arc_validate(context->vertices[edge->target].object);
    }
    for (int i = 0; i < context->vertex_count; i++) {
        __btrc_cycle_vertex* vertex = &context->vertices[i];
        if (vertex->live) continue;
        __btrc_arc_header* header = __btrc_arc_header_of(vertex->object);
        if (atomic_load_explicit(&header->rc, memory_order_acquire) != 0
                || atomic_load_explicit(&header->edge_rc, memory_order_acquire) != 0)
            __btrc_cycle_fail("dead cycle retained an owned reference");
        if (header->incoming != NULL)
            __btrc_cycle_fail("dead cycle retained an incoming owner");
        __btrc_forget_suspect(vertex->object);
        __btrc_arc_enqueue_locked(vertex->object);
    }
}
static int __btrc_collect_cycles_once(void) {
    for (;;) {
        __btrc_arc_lock_raw();
        if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
            __btrc_arc_unlock_raw();
            fprintf(stderr, "btrc: ARC operation after shutdown\n");
            exit(1);
        }
        if (__btrc_collecting
                || atomic_load_explicit(
                    &__btrc_arc_snapshot_pending, memory_order_acquire)
                || atomic_load_explicit(
                    &__btrc_arc_snapshotting, memory_order_acquire)) {
            __btrc_arc_unlock_raw();
            __btrc_arc_lock_relax();
            continue;
        }
        if (atomic_load_explicit(&__btrc_suspect_count_atomic, memory_order_acquire) == 0) {
            if (atomic_load_explicit(
                    &__btrc_arc_topology_flush_pending, memory_order_relaxed) != 0) {
                atomic_store_explicit(
                    &__btrc_arc_snapshotting, 1, memory_order_seq_cst);
                if (!__btrc_arc_any_topology_active()) {
                    atomic_store_explicit(
                        &__btrc_arc_topology_flush_pending, 0, memory_order_release);
                }
                atomic_store_explicit(
                    &__btrc_arc_snapshotting, 0, memory_order_release);
            }
            __btrc_arc_unlock_raw();
            return 0;
        }
        atomic_store_explicit(
            &__btrc_arc_snapshotting, 1, memory_order_seq_cst);
        if (__btrc_arc_any_topology_active()) {
            atomic_store_explicit(
                &__btrc_arc_topology_flush_pending, 1, memory_order_seq_cst);
            if (__btrc_arc_any_topology_active()) {
                atomic_store_explicit(
                    &__btrc_arc_snapshotting, 0, memory_order_release);
                __btrc_arc_unlock_raw();
                return 2;
            }
        }
        __btrc_collecting = 1;
        atomic_store_explicit(
            &__btrc_arc_topology_flush_pending, 0, memory_order_release);
        __btrc_arc_unlock_raw();
        break;
    }
    __btrc_arc_drain_all_mutators();

    if (__btrc_suspect_count == 0) {
        __btrc_arc_lock_raw();
        __btrc_collecting = 0;
        atomic_store_explicit(
            &__btrc_arc_snapshotting, 0, memory_order_release);
        __btrc_arc_unlock_raw();
        return 0;
    }

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
    if (__btrc_tls.arc_draining) return;
    if (!force_cycles && __btrc_tls.arc_topology_depth == 0
            && __btrc_tls.arc_deferred_head == NULL)
        return;
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    if (__btrc_tls.arc_topology_depth > 0) {
        if (force_cycles || __btrc_tls.arc_deferred_head
                || atomic_load_explicit(&__btrc_suspect_count_atomic, memory_order_acquire) > 0)
            atomic_store_explicit(&__btrc_arc_topology_flush_pending, 1, memory_order_release);
        return;
    }
    int has_terminal = __btrc_tls.arc_deferred_head != NULL;
    if (!has_terminal && !force_cycles) return;
    size_t stripe = __btrc_arc_my_stripe();
    atomic_fetch_add_explicit(
        &__btrc_arc_shared.stripes[stripe].drains, 1, memory_order_relaxed);

    __btrc_tls.arc_draining = 1;
    int cascade = 0;
    char first_error[1024];
    first_error[0] = '\0';
    __btrc_raise_fn first_raise = NULL;
    int has_error = 0;
    for (;;) {
        void* object = __btrc_tls.arc_deferred_head;
        if (object) {
            __btrc_arc_header* header = __btrc_arc_header_of(object);
            if (atomic_load_explicit(&header->state, memory_order_acquire) != __BTRC_ARC_QUEUED) {
                fprintf(stderr, "btrc: invalid deferred ARC state\n");
                exit(1);
            }
            __btrc_tls.arc_deferred_head = header->deferred_next;
            if (!__btrc_tls.arc_deferred_head)
                __btrc_tls.arc_deferred_tail = NULL;
            header->deferred_next = NULL;
            int suppress_hook = header->suppress_hook;
            header->suppress_hook = 0;
            atomic_store_explicit(&header->state, __BTRC_ARC_DESTROYING, memory_order_release);
            const __btrc_arc_type* type = header->type;
            while ((atomic_load_explicit(&header->pin_lock, memory_order_acquire)
                    & __BTRC_ARC_PIN_MASK) != 0u)
                __btrc_arc_lock_relax();

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
        int pending = atomic_load_explicit(
            &__btrc_suspect_count_atomic, memory_order_relaxed) > 0;
        int flush_req = atomic_load_explicit(
            &__btrc_arc_topology_flush_pending, memory_order_acquire) != 0;
        if (!pending && flush_req
                && !__btrc_arc_any_topology_active()
                && atomic_load_explicit(&__btrc_arc_topology_active, memory_order_relaxed) == 0)
            atomic_store_explicit(&__btrc_arc_topology_flush_pending, 0, memory_order_release);
        if (!(pending && (force_cycles || cascade || flush_req))) break;
        int collected = __btrc_collect_cycles_once();
        if (collected == 1) continue;
        break;
    }
    __btrc_tls.arc_draining = 0;
    if (atomic_fetch_sub_explicit(
            &__btrc_arc_shared.stripes[stripe].drains, 1, memory_order_release) <= 0) {
        fprintf(stderr, "btrc: invalid ARC drain count\n");
        exit(1);
    }
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
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_relaxed)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    if (atomic_load_explicit(&__btrc_suspect_count_atomic, memory_order_relaxed) >= 256)
        __btrc_arc_drain_deferred(1);
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
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        fprintf(stderr, "btrc: ARC operation after shutdown\n");
        exit(1);
    }
    if (__btrc_tls.tracking != 0
            || __btrc_tls.arc_topology_depth != 0
            || __btrc_tls.arc_draining
            || __btrc_tls.arc_deferred_head
            || __btrc_tls.arc_deferred_tail
            || __btrc_tls.abandon_queue
            || __btrc_tls.abandon_count != 0
            || __btrc_tls.abandon_drain_callback) {
        fprintf(stderr, "btrc: ARC thread cleanup during active work\n");
        exit(1);
    }
    free(__btrc_tls.destroyed);
    __btrc_tls.destroyed = NULL;
    __btrc_tls.destroyed_count = 0;
    __btrc_tls.destroyed_cap = 0;
    free(__btrc_tls.abandon_queue);
    __btrc_tls.abandon_queue = NULL;
    __btrc_tls.abandon_count = 0;
    __btrc_tls.abandon_cap = 0;
    __btrc_tls.abandon_drain_callback = NULL;
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
    if (atomic_load_explicit(&__btrc_arc_shutdown, memory_order_acquire)) {
        __btrc_arc_unlock_raw();
        fprintf(stderr, "btrc: repeated ARC shutdown\n");
        exit(1);
    }
    atomic_store_explicit(&__btrc_arc_shutdown, 1, memory_order_seq_cst);
    __btrc_arc_drain_all_mutators();
    int active_work = 0;
    for (size_t i = 0; i < __BTRC_ARC_STRIPE_COUNT; i++) {
        if (atomic_load_explicit(
                    &__btrc_arc_shared.stripes[i].drains, memory_order_acquire) != 0
                || atomic_load_explicit(
                    &__btrc_arc_shared.stripes[i].unwinds, memory_order_acquire) != 0) {
            active_work = 1;
            break;
        }
    }
    if (active_work
            || atomic_load_explicit(
                &__btrc_arc_snapshotting, memory_order_acquire) != 0
            || atomic_load_explicit(
                &__btrc_arc_snapshot_pending, memory_order_acquire) != 0
            || __btrc_collecting != 0) {
        fprintf(stderr, "btrc: ARC cleanup during active work\n");
        exit(1);
    }
    if (__btrc_arc_any_topology_active()
            || atomic_load_explicit(&__btrc_arc_topology_active, memory_order_acquire) != 0) {
        fprintf(stderr, "btrc: ARC cleanup during topology mutation\n");
        exit(1);
    }
    free(__btrc_suspects);
    free(__btrc_visit_table);
    free(__btrc_destroy_table);
    free(__btrc_suspect_keys);
    free(__btrc_suspect_slots);
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
    __btrc_suspect_slots = NULL;
    __btrc_reverse_queue = NULL;
    __btrc_reverse_keys = NULL;
    __btrc_reverse_marks = NULL;
    __btrc_suspect_count = __btrc_suspect_cap = 0;
    atomic_store_explicit(&__btrc_suspect_count_atomic, 0, memory_order_release);
    __btrc_suspect_key_cap = 0;
    __btrc_reverse_queue_cap = __btrc_reverse_key_cap = 0;
    atomic_store_explicit(&__btrc_reverse_count, 0, memory_order_release);
    __btrc_reverse_epoch = 0;
    if (__btrc_tls.arc_deferred_head || __btrc_tls.arc_deferred_tail
            || __btrc_tls.arc_draining) {
        fprintf(stderr, "btrc: ARC cleanup during active drain\n");
        exit(1);
    }
    atomic_store_explicit(&__btrc_arc_topology_flush_pending, 0, memory_order_release);
    __btrc_collecting = 0;
    __btrc_arc_unlock_raw();
}
/* btrc-runtime-helper:end __btrc_cycle_state_cleanup */
