#include <limits.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* BTRC_RUNTIME_HELPERS */

#define MAX_NODE_IDS 2048

typedef struct Barrier {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    int parties;
    int arrived;
    int generation;
} Barrier;

static void barrier_init(Barrier* barrier, int parties) {
    if (pthread_mutex_init(&barrier->mutex, NULL)) abort();
    if (pthread_cond_init(&barrier->condition, NULL)) abort();
    barrier->parties = parties;
    barrier->arrived = 0;
    barrier->generation = 0;
}

static void barrier_wait(Barrier* barrier) {
    if (pthread_mutex_lock(&barrier->mutex)) abort();
    int generation = barrier->generation;
    barrier->arrived++;
    if (barrier->arrived == barrier->parties) {
        barrier->arrived = 0;
        barrier->generation++;
        if (pthread_cond_broadcast(&barrier->condition)) abort();
    } else {
        while (generation == barrier->generation) {
            if (pthread_cond_wait(
                    &barrier->condition, &barrier->mutex)) abort();
        }
    }
    if (pthread_mutex_unlock(&barrier->mutex)) abort();
}

static void barrier_destroy(Barrier* barrier) {
    if (pthread_cond_destroy(&barrier->condition)) abort();
    if (pthread_mutex_destroy(&barrier->mutex)) abort();
}

typedef struct Node {
    __btrc_arc_header arc;
    struct Node* next;
    struct Node* alternate;
    int id;
    int recycle;
} Node;

static const __btrc_arc_type node_type;
static _Atomic int hook_counts[MAX_NODE_IDS];
static _Atomic int destroy_counts[MAX_NODE_IDS];
static _Thread_local jmp_buf* raise_target;
static _Thread_local int release_thread_index = -1;
static _Thread_local int* cascade_trace;
static _Thread_local int cascade_trace_length;
static _Atomic int terminal_hook_thread = -1;
static pthread_mutex_t terminal_overlap_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t terminal_overlap_condition = PTHREAD_COND_INITIALIZER;
static int terminal_overlap_entered;
static int terminal_overlap_continue;

static pthread_mutex_t recycle_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t recycle_condition = PTHREAD_COND_INITIALIZER;
static Node* recycled_node;
static int recycle_events;
static _Atomic uintptr_t first_recycled_address;

static void recycle_storage(Node* node) {
    if (pthread_mutex_lock(&recycle_mutex)) abort();
    if (recycled_node) abort();
    recycled_node = node;
    recycle_events++;
    if (pthread_cond_broadcast(&recycle_condition)) abort();
    if (pthread_mutex_unlock(&recycle_mutex)) abort();
}

static void* node_slot_access(
        volatile void* raw, void* expected, void* replacement, int commit) {
    Node* volatile* slot = (Node* volatile*)raw;
    Node* current = *slot;
    if (commit && current == (Node*)expected)
        *slot = (Node*)replacement;
    return (void*)current;
}

static void node_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {
    Node* node = (Node*)raw;
    visit((volatile void*)&node->next, node_slot_access, &node_type, context);
    visit((volatile void*)&node->alternate,
        node_slot_access, &node_type, context);
}

static void node_hook(void* raw) {
    Node* node = (Node*)raw;
    if (node->id < 0 || node->id >= MAX_NODE_IDS) abort();
    if (atomic_fetch_add_explicit(
            &hook_counts[node->id], 1, memory_order_relaxed) != 0) abort();
    if (release_thread_index >= 0 && node->id == 1) {
        atomic_store_explicit(
            &terminal_hook_thread, release_thread_index,
            memory_order_relaxed);
    }
    if (cascade_trace) {
        if (cascade_trace_length >= 3) abort();
        cascade_trace[cascade_trace_length++] = node->id;
    }
    if (node->id == 1000) {
        if (pthread_mutex_lock(&terminal_overlap_mutex)) abort();
        terminal_overlap_entered = 1;
        if (pthread_cond_broadcast(&terminal_overlap_condition)) abort();
        while (!terminal_overlap_continue) {
            if (pthread_cond_wait(
                    &terminal_overlap_condition,
                    &terminal_overlap_mutex)) abort();
        }
        if (pthread_mutex_unlock(&terminal_overlap_mutex)) abort();
    }
}

static int node_hook_guard(
        __btrc_hook_fn hook, void* object,
        char* error, size_t error_capacity) {
    if (error && error_capacity) error[0] = '\0';
    hook(object);
    return 0;
}

static _Noreturn void node_raise(const char* message) {
    (void)message;
    if (!raise_target) abort();
    longjmp(*raise_target, 1);
}

static void node_destroy(void* raw) {
    Node* node = (Node*)raw;
    int id = node->id;
    int recycle = node->recycle;
    if (id < 0 || id >= MAX_NODE_IDS) abort();
    if (atomic_fetch_add_explicit(
            &destroy_counts[id], 1, memory_order_relaxed) != 0) abort();
    __btrc_arc_replace_edge(
        (volatile void*)&node->next, node_slot_access,
        NULL, node, &node_type, 0);
    __btrc_arc_replace_edge(
        (volatile void*)&node->alternate, node_slot_access,
        NULL, node, &node_type, 0);
    __btrc_mark_destroyed(node);
    if (recycle) {
        recycle_storage(node);
    } else {
        free(node);
    }
}

static const __btrc_arc_type node_type = {
    .visit = node_visit,
    .destroy = node_destroy,
    .hook = node_hook,
    .guard = node_hook_guard,
    .raise = node_raise,
};

static void initialize_node(Node* node, int id, int recycle) {
    memset(node, 0, sizeof(*node));
    node->arc.rc = 1;
    node->arc.type = &node_type;
    node->arc.state = __BTRC_ARC_LIVE;
    node->id = id;
    node->recycle = recycle;
}

static Node* new_node(int id) {
    Node* node = (Node*)__btrc_safe_calloc(1, sizeof(Node));
    initialize_node(node, id, 0);
    return node;
}

static Node* new_recyclable_node(int id) {
    Node* node = (Node*)__btrc_safe_calloc(1, sizeof(Node));
    initialize_node(node, id, 1);
    return node;
}

static Node* take_recycled_node(int id) {
    if (pthread_mutex_lock(&recycle_mutex)) abort();
    while (!recycled_node) {
        if (pthread_cond_wait(
                &recycle_condition, &recycle_mutex)) abort();
    }
    Node* node = recycled_node;
    recycled_node = NULL;
    if (pthread_mutex_unlock(&recycle_mutex)) abort();
    initialize_node(node, id, 1);
    return node;
}

static void adopt_slot(Node* owner, Node* volatile* slot, Node* value) {
    if (__btrc_arc_replace_edge(
            (volatile void*)slot, node_slot_access,
            value, owner, &node_type, 1) != 0) abort();
}

static int count_for(_Atomic int* counters, int id) {
    return atomic_load_explicit(&counters[id], memory_order_relaxed);
}

typedef struct RootReleaseArgs {
    Barrier* start;
    Node* node;
    int index;
    int observed_own_hook;
} RootReleaseArgs;

static void* root_release_worker(void* raw) {
    RootReleaseArgs* args = (RootReleaseArgs*)raw;
    release_thread_index = args->index;
    barrier_wait(args->start);
    __btrc_arc_release(args->node, &node_type);
    args->observed_own_hook = atomic_load_explicit(
        &terminal_hook_thread, memory_order_relaxed) == args->index;
    release_thread_index = -1;
    return NULL;
}

static void test_simultaneous_final_release(void) {
    Node* node = new_node(1);
    node->arc.rc = 2;
    Barrier start;
    barrier_init(&start, 2);
    RootReleaseArgs args[2] = {
        {&start, node, 0, 0},
        {&start, node, 1, 0},
    };
    pthread_t workers[2];
    if (pthread_create(
            &workers[0], NULL, root_release_worker, &args[0])) abort();
    if (pthread_create(
            &workers[1], NULL, root_release_worker, &args[1])) abort();
    if (pthread_join(workers[0], NULL)) abort();
    if (pthread_join(workers[1], NULL)) abort();
    barrier_destroy(&start);
    if (count_for(hook_counts, 1) != 1
            || count_for(destroy_counts, 1) != 1) abort();
    int hook_thread = atomic_load_explicit(
        &terminal_hook_thread, memory_order_relaxed);
    if (hook_thread < 0 || hook_thread > 1) abort();
    if (args[0].observed_own_hook + args[1].observed_own_hook != 1) abort();
    if (!args[hook_thread].observed_own_hook) abort();
}

typedef struct CascadeArgs {
    Barrier* start;
    Node* root;
    int trace[3];
    int trace_length;
} CascadeArgs;

static void* cascade_worker(void* raw) {
    CascadeArgs* args = (CascadeArgs*)raw;
    cascade_trace = args->trace;
    cascade_trace_length = 0;
    barrier_wait(args->start);
    __btrc_arc_release(args->root, &node_type);
    args->trace_length = cascade_trace_length;
    cascade_trace = NULL;
    cascade_trace_length = 0;
    return NULL;
}

static Node* make_cascade(int base) {
    Node* root = new_node(base);
    Node* first = new_node(base + 1);
    Node* second = new_node(base + 2);
    adopt_slot(root, &root->next, first);
    adopt_slot(root, &root->alternate, second);
    return root;
}

static void test_independent_fifo_cascades(void) {
    Barrier start;
    barrier_init(&start, 2);
    CascadeArgs args[2] = {
        {.start = &start, .root = make_cascade(100)},
        {.start = &start, .root = make_cascade(200)},
    };
    pthread_t workers[2];
    if (pthread_create(
            &workers[0], NULL, cascade_worker, &args[0])) abort();
    if (pthread_create(
            &workers[1], NULL, cascade_worker, &args[1])) abort();
    if (pthread_join(workers[0], NULL)) abort();
    if (pthread_join(workers[1], NULL)) abort();
    barrier_destroy(&start);
    for (int worker = 0; worker < 2; worker++) {
        int base = worker ? 200 : 100;
        if (args[worker].trace_length != 3) abort();
        for (int index = 0; index < 3; index++) {
            if (args[worker].trace[index] != base + index) abort();
            if (count_for(hook_counts, base + index) != 1
                    || count_for(destroy_counts, base + index) != 1) abort();
        }
    }
}

typedef struct ReuseArgs {
    Barrier* active;
    int failed;
} ReuseArgs;

static void* first_unwind_worker(void* raw) {
    ReuseArgs* args = (ReuseArgs*)raw;
    __btrc_destroyed_tracking_begin();
    barrier_wait(args->active);
    Node* node = new_recyclable_node(300);
    atomic_store_explicit(
        &first_recycled_address, (uintptr_t)node, memory_order_release);
    __btrc_arc_release(node, &node_type);
    if (!__btrc_is_destroyed(node)) args->failed = 1;
    if (pthread_mutex_lock(&recycle_mutex)) abort();
    while (recycle_events < 2) {
        if (pthread_cond_wait(
                &recycle_condition, &recycle_mutex)) abort();
    }
    if (pthread_mutex_unlock(&recycle_mutex)) abort();
    __btrc_destroyed_tracking_end();
    __btrc_arc_thread_state_cleanup();
    return NULL;
}

static void* second_unwind_worker(void* raw) {
    ReuseArgs* args = (ReuseArgs*)raw;
    __btrc_destroyed_tracking_begin();
    barrier_wait(args->active);
    Node* node = take_recycled_node(301);
    if ((uintptr_t)node != atomic_load_explicit(
            &first_recycled_address, memory_order_acquire)) args->failed = 1;
    if (__btrc_is_destroyed(node)) args->failed = 1;
    if (!__btrc_is_destroyed(node))
        __btrc_arc_release(node, &node_type);
    __btrc_destroyed_tracking_end();
    __btrc_arc_thread_state_cleanup();
    return NULL;
}

static void test_destroy_tracking_address_reuse(void) {
    Barrier active;
    barrier_init(&active, 2);
    ReuseArgs args[2] = {
        {.active = &active},
        {.active = &active},
    };
    pthread_t workers[2];
    if (pthread_create(
            &workers[0], NULL, first_unwind_worker, &args[0])) abort();
    if (pthread_create(
            &workers[1], NULL, second_unwind_worker, &args[1])) abort();
    if (pthread_join(workers[0], NULL)) abort();
    if (pthread_join(workers[1], NULL)) abort();
    barrier_destroy(&active);
    if (args[0].failed || args[1].failed) abort();
    if (count_for(destroy_counts, 300) != 1
            || count_for(destroy_counts, 301) != 1) abort();
    if (pthread_mutex_lock(&recycle_mutex)) abort();
    Node* storage = recycled_node;
    recycled_node = NULL;
    if (pthread_mutex_unlock(&recycle_mutex)) abort();
    if (!storage || recycle_events != 2) abort();
    free(storage);
}

typedef struct RootTransactionArgs {
    Barrier* phases;
    Node* object;
    Node* volatile* slot;
    _Atomic int retain_success;
    _Atomic int retain_error;
    _Atomic int delete_success;
    _Atomic int delete_error;
} RootTransactionArgs;

static void* transaction_retain_worker(void* raw) {
    RootTransactionArgs* args = (RootTransactionArgs*)raw;
    void* volatile topology = __btrc_arc_topology_begin();
    barrier_wait(args->phases);
    jmp_buf jump;
    raise_target = &jump;
    if (setjmp(jump) == 0) {
        __btrc_arc_retain(args->object);
        atomic_store_explicit(
            &args->retain_success, 1, memory_order_relaxed);
    } else {
        atomic_store_explicit(
            &args->retain_error, 1, memory_order_relaxed);
    }
    raise_target = NULL;
    barrier_wait(args->phases);
    __btrc_arc_topology_complete(&topology);
    return NULL;
}

static void* transaction_delete_worker(void* raw) {
    RootTransactionArgs* args = (RootTransactionArgs*)raw;
    void* volatile topology = __btrc_arc_topology_begin();
    barrier_wait(args->phases);
    jmp_buf jump;
    raise_target = &jump;
    if (setjmp(jump) == 0) {
        __btrc_arc_destroy_slot(
            (volatile void*)args->slot, node_slot_access, &node_type);
        atomic_store_explicit(
            &args->delete_success, 1, memory_order_relaxed);
    } else {
        atomic_store_explicit(
            &args->delete_error, 1, memory_order_relaxed);
    }
    raise_target = NULL;
    barrier_wait(args->phases);
    __btrc_arc_topology_complete(&topology);
    return NULL;
}

static void test_retain_vs_delete_transaction(void) {
    Node* object = new_node(400);
    Node* volatile slot = object;
    Barrier phases;
    barrier_init(&phases, 2);
    RootTransactionArgs args = {
        .phases = &phases,
        .object = object,
        .slot = &slot,
    };
    pthread_t retain_worker;
    pthread_t delete_worker;
    if (pthread_create(&retain_worker, NULL,
            transaction_retain_worker, &args)) abort();
    if (pthread_create(&delete_worker, NULL,
            transaction_delete_worker, &args)) abort();
    if (pthread_join(retain_worker, NULL)) abort();
    if (pthread_join(delete_worker, NULL)) abort();
    barrier_destroy(&phases);
    int retained = atomic_load_explicit(
        &args.retain_success, memory_order_relaxed);
    int retain_error = atomic_load_explicit(
        &args.retain_error, memory_order_relaxed);
    int deleted = atomic_load_explicit(
        &args.delete_success, memory_order_relaxed);
    int delete_error = atomic_load_explicit(
        &args.delete_error, memory_order_relaxed);
    if (retained && delete_error && !deleted && !retain_error) {
        if (slot != object) abort();
        __btrc_arc_release(object, &node_type);
        __btrc_arc_destroy_slot(
            (volatile void*)&slot, node_slot_access, &node_type);
    } else if (deleted && retain_error && !retained && !delete_error) {
        if (slot != NULL) abort();
    } else {
        abort();
    }
    if (count_for(hook_counts, 400) != 1
            || count_for(destroy_counts, 400) != 1) abort();
}

typedef struct EdgeTransactionArgs {
    Barrier* phases;
    Node* owner;
    Node* replacement;
    _Atomic int replace_success;
    _Atomic int replace_error;
    _Atomic int delete_success;
    _Atomic int delete_error;
} EdgeTransactionArgs;

static void* transaction_replace_worker(void* raw) {
    EdgeTransactionArgs* args = (EdgeTransactionArgs*)raw;
    void* volatile topology = __btrc_arc_topology_begin();
    barrier_wait(args->phases);
    jmp_buf jump;
    raise_target = &jump;
    if (setjmp(jump) == 0) {
        __btrc_arc_replace_edge(
            (volatile void*)&args->owner->next, node_slot_access,
            args->replacement, args->owner, &node_type, 1);
        atomic_store_explicit(
            &args->replace_success, 1, memory_order_relaxed);
    } else {
        atomic_store_explicit(
            &args->replace_error, 1, memory_order_relaxed);
    }
    raise_target = NULL;
    barrier_wait(args->phases);
    __btrc_arc_topology_complete(&topology);
    return NULL;
}

static void* transaction_edge_delete_worker(void* raw) {
    EdgeTransactionArgs* args = (EdgeTransactionArgs*)raw;
    void* volatile topology = __btrc_arc_topology_begin();
    barrier_wait(args->phases);
    jmp_buf jump;
    raise_target = &jump;
    if (setjmp(jump) == 0) {
        __btrc_arc_destroy_edge(
            (volatile void*)&args->owner->next, node_slot_access,
            args->owner, &node_type);
        atomic_store_explicit(
            &args->delete_success, 1, memory_order_relaxed);
    } else {
        atomic_store_explicit(
            &args->delete_error, 1, memory_order_relaxed);
    }
    raise_target = NULL;
    barrier_wait(args->phases);
    __btrc_arc_topology_complete(&topology);
    return NULL;
}

static void test_replace_vs_persistent_delete_transaction(void) {
    Node* owner = new_node(500);
    Node* old = new_node(501);
    Node* replacement = new_node(502);
    adopt_slot(owner, &owner->next, old);
    Barrier phases;
    barrier_init(&phases, 2);
    EdgeTransactionArgs args = {
        .phases = &phases,
        .owner = owner,
        .replacement = replacement,
    };
    pthread_t replace_worker;
    pthread_t delete_worker;
    if (pthread_create(&replace_worker, NULL,
            transaction_replace_worker, &args)) abort();
    if (pthread_create(&delete_worker, NULL,
            transaction_edge_delete_worker, &args)) abort();
    if (pthread_join(replace_worker, NULL)) abort();
    if (pthread_join(delete_worker, NULL)) abort();
    barrier_destroy(&phases);
    if (!atomic_load_explicit(
            &args.replace_success, memory_order_relaxed)
            || atomic_load_explicit(
                &args.replace_error, memory_order_relaxed)
            || !atomic_load_explicit(
                &args.delete_success, memory_order_relaxed)
            || atomic_load_explicit(
                &args.delete_error, memory_order_relaxed)) abort();
    if (count_for(destroy_counts, 501) != 1) abort();
    Node* survivor = owner->next;
    if (survivor == replacement) {
        if (count_for(destroy_counts, 502) != 0) abort();
        __btrc_arc_destroy_edge(
            (volatile void*)&owner->next, node_slot_access,
            owner, &node_type);
    } else if (survivor != NULL) {
        abort();
    }
    if (count_for(hook_counts, 501) != 1
            || count_for(hook_counts, 502) != 1
            || count_for(destroy_counts, 502) != 1) abort();
    __btrc_arc_release(owner, &node_type);
    if (count_for(destroy_counts, 500) != 1) abort();
}

typedef struct CollectorRaceArgs {
    Barrier* start;
    Node* root;
} CollectorRaceArgs;

static void* final_release_worker(void* raw) {
    CollectorRaceArgs* args = (CollectorRaceArgs*)raw;
    barrier_wait(args->start);
    __btrc_arc_release(args->root, &node_type);
    return NULL;
}

static void* collector_worker(void* raw) {
    CollectorRaceArgs* args = (CollectorRaceArgs*)raw;
    barrier_wait(args->start);
    __btrc_collect_cycles();
    return NULL;
}

static void test_collector_vs_final_release(void) {
    for (int iteration = 0; iteration < 96; iteration++) {
        int first_id = 600 + iteration * 2;
        int second_id = first_id + 1;
        Node* first = new_node(first_id);
        Node* second = new_node(second_id);
        adopt_slot(first, &first->next, second);
        if (__btrc_arc_replace_edge(
                (volatile void*)&second->next, node_slot_access,
                first, second, &node_type, 0) != 0) abort();
        __btrc_arc_release(first, &node_type);
        __btrc_arc_retain(first);
        Barrier start;
        barrier_init(&start, 2);
        CollectorRaceArgs args = {&start, first};
        pthread_t releaser;
        pthread_t collector;
        if (pthread_create(
                &releaser, NULL, final_release_worker, &args)) abort();
        if (pthread_create(
                &collector, NULL, collector_worker, &args)) abort();
        if (pthread_join(releaser, NULL)) abort();
        if (pthread_join(collector, NULL)) abort();
        barrier_destroy(&start);
        __btrc_flush_cycles();
        if (count_for(hook_counts, first_id) != 1
                || count_for(hook_counts, second_id) != 1
                || count_for(destroy_counts, first_id) != 1
                || count_for(destroy_counts, second_id) != 1) abort();
    }
}

static void* terminal_cycle_release_worker(void* raw) {
    __btrc_arc_release(raw, &node_type);
    return NULL;
}

static void test_snapshot_during_terminal_cycle_drain(void) {
    Node* root = new_node(1000);
    Node* first = new_node(1001);
    Node* second = new_node(1002);
    adopt_slot(first, &first->next, second);
    if (__btrc_arc_replace_edge(
            (volatile void*)&second->next, node_slot_access,
            first, second, &node_type, 0) != 0) abort();
    __btrc_arc_release(first, &node_type);
    if (__btrc_suspect_count != 1) abort();
    if (__btrc_arc_replace_edge(
            (volatile void*)&root->next, node_slot_access,
            first, root, &node_type, 0) != 0) abort();

    terminal_overlap_entered = 0;
    terminal_overlap_continue = 0;
    pthread_t releaser;
    if (pthread_create(
            &releaser, NULL, terminal_cycle_release_worker, root)) abort();
    if (pthread_mutex_lock(&terminal_overlap_mutex)) abort();
    while (!terminal_overlap_entered) {
        if (pthread_cond_wait(
                &terminal_overlap_condition,
                &terminal_overlap_mutex)) abort();
    }
    if (pthread_mutex_unlock(&terminal_overlap_mutex)) abort();

    /* The terminal owner is already DESTROYING but still owns `first` while
     * its hook is paused. A concurrent snapshot may classify the downstream
     * cycle, but the owner's unscanned edge must keep both nodes live. */
    if (root->arc.state != __BTRC_ARC_DESTROYING
            || __btrc_arc_active_drains != 1) abort();
    __btrc_collect_cycles();
    if (count_for(destroy_counts, 1000) != 0
            || count_for(destroy_counts, 1001) != 0
            || count_for(destroy_counts, 1002) != 0
            || first->arc.state != __BTRC_ARC_LIVE
            || second->arc.state != __BTRC_ARC_LIVE
            || __btrc_arc_active_drains != 1) abort();

    if (pthread_mutex_lock(&terminal_overlap_mutex)) abort();
    terminal_overlap_continue = 1;
    if (pthread_cond_broadcast(&terminal_overlap_condition)) abort();
    if (pthread_mutex_unlock(&terminal_overlap_mutex)) abort();
    if (pthread_join(releaser, NULL)) abort();
    if (count_for(hook_counts, 1000) != 1
            || count_for(hook_counts, 1001) != 1
            || count_for(hook_counts, 1002) != 1
            || count_for(destroy_counts, 1000) != 1
            || count_for(destroy_counts, 1001) != 1
            || count_for(destroy_counts, 1002) != 1) abort();
}

int main(void) {
    test_simultaneous_final_release();
    test_independent_fifo_cascades();
    test_destroy_tracking_address_reuse();
    test_retain_vs_delete_transaction();
    test_replace_vs_persistent_delete_transaction();
    test_collector_vs_final_release();
    test_snapshot_during_terminal_cycle_drain();
    __btrc_cycle_state_cleanup();
    return 0;
}
