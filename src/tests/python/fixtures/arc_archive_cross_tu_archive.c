#include "btrc_stdlib.h"

typedef struct CrossChild CrossChild;

typedef struct CrossOwner {
    __btrc_arc_header arc;
    CrossChild* first;
    CrossChild* second;
} CrossOwner;

extern const __btrc_arc_type cross_program_child_type;
extern CrossChild* cross_program_child_new(int id);
extern void cross_record_hook(int id);
extern void cross_record_destroy(int id);
extern _Noreturn void cross_raise(const char* message);

static void copy_error(
        char* error, size_t capacity, const char* message) {
    if (!error || capacity == 0) return;
    size_t length = strlen(message);
    if (length >= capacity) length = capacity - 1;
    memcpy(error, message, length);
    error[length] = '\0';
}

static void* child_slot_access(
        volatile void* raw, void* expected, void* replacement, int commit) {
    CrossChild* volatile* slot = (CrossChild* volatile*)raw;
    CrossChild* current = *slot;
    if (commit && current == (CrossChild*)expected)
        *slot = (CrossChild*)replacement;
    return (void*)current;
}

static void owner_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {
    CrossOwner* owner = (CrossOwner*)raw;
    visit((volatile void*)&owner->first,
        child_slot_access, &cross_program_child_type, context);
    visit((volatile void*)&owner->second,
        child_slot_access, &cross_program_child_type, context);
}

static void owner_hook(void* raw) {
    (void)raw;
    cross_record_hook(1);
}

static int owner_hook_guard(
        __btrc_hook_fn hook, void* object,
        char* error, size_t error_capacity) {
    hook(object);
    copy_error(error, error_capacity, "archive owner hook failure");
    return 1;
}

static void owner_destroy(void* raw) {
    CrossOwner* owner = (CrossOwner*)raw;
    __btrc_arc_replace_edge(
        (volatile void*)&owner->first, child_slot_access,
        NULL, owner, &cross_program_child_type, 0);
    __btrc_arc_replace_edge(
        (volatile void*)&owner->second, child_slot_access,
        NULL, owner, &cross_program_child_type, 0);
    cross_record_destroy(1);
    __btrc_mark_destroyed(owner);
    free(owner);
}

static const __btrc_arc_type archive_owner_type = {
    .visit = owner_visit,
    .destroy = owner_destroy,
    .hook = owner_hook,
    .guard = owner_hook_guard,
    .raise = cross_raise,
};

void* archive_make_cross_owner(void) {
    CrossOwner* owner = (CrossOwner*)__btrc_safe_calloc(
        1, sizeof(CrossOwner));
    owner->arc.rc = 1;
    owner->arc.type = &archive_owner_type;
    owner->arc.state = __BTRC_ARC_LIVE;
    CrossChild* first = cross_program_child_new(2);
    CrossChild* second = cross_program_child_new(3);
    __btrc_arc_replace_edge(
        (volatile void*)&owner->first, child_slot_access,
        first, owner, &cross_program_child_type, 1);
    __btrc_arc_replace_edge(
        (volatile void*)&owner->second, child_slot_access,
        second, owner, &cross_program_child_type, 1);
    return owner;
}

void* archive_arc_tls_address(int index) {
    switch (index) {
        case 0: return (void*)&__btrc_arc_deferred_head;
        case 1: return (void*)&__btrc_arc_deferred_tail;
        case 2: return (void*)&__btrc_arc_draining;
        case 3: return (void*)&__btrc_arc_topology_depth;
        case 4: return (void*)&__btrc_tracking;
        case 5: return (void*)&__btrc_destroyed;
        case 6: return (void*)&__btrc_destroyed_count;
        case 7: return (void*)&__btrc_destroyed_cap;
        case 8: return (void*)&__btrc_abandon_queue;
        case 9: return (void*)&__btrc_abandon_count;
        case 10: return (void*)&__btrc_abandon_cap;
        case 11: return (void*)&__btrc_abandon_drain_callback;
        default: return NULL;
    }
}

void* archive_arc_process_address(int index) {
    switch (index) {
        case 0: return (void*)&__btrc_arc_lock_flag;
        case 1: return (void*)&__btrc_arc_snapshotting;
        case 2: return (void*)&__btrc_arc_topology_active;
        case 3: return (void*)&__btrc_suspects;
        case 4: return (void*)&__btrc_cycle_scratch;
        case 5: return (void*)&__btrc_arc_shutdown;
        case 6: return (void*)&__btrc_arc_snapshot_pending;
        default: return NULL;
    }
}

int archive_arc_tls_is_idle(void) {
    return __btrc_arc_deferred_head == NULL
        && __btrc_arc_deferred_tail == NULL
        && __btrc_arc_draining == 0
        && __btrc_arc_topology_depth == 0
        && __btrc_abandon_queue == NULL
        && __btrc_abandon_count == 0
        && __btrc_abandon_cap == 0
        && __btrc_abandon_drain_callback == NULL
        && atomic_load_explicit(
            &__btrc_arc_snapshot_pending, memory_order_acquire) == 0;
}

int archive_arc_new_state_matches(
        void** queue, int count, int cap, int has_callback,
        int snapshot_pending) {
    return __btrc_abandon_queue == queue
        && __btrc_abandon_count == count
        && __btrc_abandon_cap == cap
        && (__btrc_abandon_drain_callback != NULL) == has_callback
        && atomic_load_explicit(
            &__btrc_arc_snapshot_pending,
            memory_order_acquire) == snapshot_pending;
}

void archive_arc_clear_new_state(void) {
    __btrc_abandon_queue = NULL;
    __btrc_abandon_count = 0;
    __btrc_abandon_cap = 0;
    __btrc_abandon_drain_callback = NULL;
    atomic_store_explicit(
        &__btrc_arc_snapshot_pending, 0, memory_order_release);
}
