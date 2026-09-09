#include "btrc_stdlib.h"

#include <setjmp.h>

typedef struct CrossChild {
    __btrc_arc_header arc;
    int id;
} CrossChild;

void* archive_make_cross_owner(void);
void* archive_arc_tls_address(int index);
void* archive_arc_process_address(int index);
int archive_arc_tls_is_idle(void);
int archive_arc_new_state_matches(
    void** queue, int count, int cap, int has_callback,
    int snapshot_pending);
void archive_arc_clear_new_state(void);

static int hook_trace[3];
static int hook_trace_length;
static int destroy_counts[4];
static _Thread_local jmp_buf* jump_target;
static char raised_error[128];

static void noop_abandon_drain(void) {}

static void copy_error(
        char* error, size_t capacity, const char* message) {
    if (!error || capacity == 0) return;
    size_t length = strlen(message);
    if (length >= capacity) length = capacity - 1;
    memcpy(error, message, length);
    error[length] = '\0';
}

void cross_record_hook(int id) {
    if (hook_trace_length >= 3) abort();
    hook_trace[hook_trace_length++] = id;
}

void cross_record_destroy(int id) {
    if (id < 1 || id > 3 || destroy_counts[id]++) abort();
}

_Noreturn void cross_raise(const char* message) {
    if (!jump_target) abort();
    copy_error(raised_error, sizeof raised_error, message);
    longjmp(*jump_target, 1);
}

static void child_visit(
        void* object, __btrc_field_visit_fn visit, void* context) {
    (void)object;
    (void)visit;
    (void)context;
}

static void child_hook(void* raw) {
    CrossChild* child = (CrossChild*)raw;
    cross_record_hook(child->id);
}

static int child_hook_guard(
        __btrc_hook_fn hook, void* object,
        char* error, size_t error_capacity) {
    hook(object);
    copy_error(error, error_capacity, "program child hook failure");
    return 1;
}

static void child_destroy(void* raw) {
    CrossChild* child = (CrossChild*)raw;
    cross_record_destroy(child->id);
    __btrc_mark_destroyed(child);
    free(child);
}

const __btrc_arc_type cross_program_child_type = {
    .visit = child_visit,
    .destroy = child_destroy,
    .hook = child_hook,
    .guard = child_hook_guard,
    .raise = cross_raise,
};

CrossChild* cross_program_child_new(int id) {
    CrossChild* child = (CrossChild*)__btrc_safe_calloc(
        1, sizeof(CrossChild));
    child->arc.rc = 1;
    child->arc.type = &cross_program_child_type;
    child->arc.state = __BTRC_ARC_LIVE;
    child->id = id;
    return child;
}

static void* program_arc_tls_address(int index) {
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

static void* program_arc_process_address(int index) {
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

int main(void) {
    for (int index = 0; index < 12; index++) {
        if (archive_arc_tls_address(index)
                != program_arc_tls_address(index)) return 10 + index;
    }
    for (int index = 0; index < 7; index++) {
        if (archive_arc_process_address(index)
                != program_arc_process_address(index)) return 20 + index;
    }

    void* abandon_probe[3] = {NULL, NULL, NULL};
    __btrc_abandon_queue = abandon_probe;
    __btrc_abandon_count = 2;
    __btrc_abandon_cap = 3;
    __btrc_abandon_drain_callback = noop_abandon_drain;
    atomic_store_explicit(
        &__btrc_arc_snapshot_pending, 1, memory_order_release);
    if (!archive_arc_new_state_matches(
            abandon_probe, 2, 3, 1, 1)) return 27;
    archive_arc_clear_new_state();
    if (__btrc_abandon_queue != NULL
            || __btrc_abandon_count != 0
            || __btrc_abandon_cap != 0
            || __btrc_abandon_drain_callback != NULL
            || atomic_load_explicit(
                &__btrc_arc_snapshot_pending,
                memory_order_acquire) != 0) return 28;

    void* owner = archive_make_cross_owner();
    jmp_buf jump;
    jump_target = &jump;
    if (setjmp(jump) == 0) {
        __btrc_arc_release(owner, NULL);
        return 30;
    }
    jump_target = NULL;

    if (strcmp(raised_error, "archive owner hook failure") != 0) return 31;
    if (hook_trace_length != 3
            || hook_trace[0] != 1
            || hook_trace[1] != 2
            || hook_trace[2] != 3) return 32;
    if (destroy_counts[1] != 1
            || destroy_counts[2] != 1
            || destroy_counts[3] != 1) return 33;
    if (!archive_arc_tls_is_idle()
            || __btrc_arc_deferred_head != NULL
            || __btrc_arc_deferred_tail != NULL
            || __btrc_arc_draining != 0) return 34;
    __btrc_flush_cycles();
    if (hook_trace_length != 3) return 35;
    __btrc_cycle_state_cleanup();
    return 0;
}
