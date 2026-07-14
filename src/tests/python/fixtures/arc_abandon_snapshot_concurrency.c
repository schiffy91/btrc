#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* BTRC_RUNTIME_HELPERS */

typedef struct Barrier {
    pthread_mutex_t lock;
    pthread_cond_t condition;
    int arrived;
    int parties;
    int generation;
} Barrier;

static void barrier_init(Barrier* barrier, int parties) {
    if (pthread_mutex_init(&barrier->lock, NULL)) abort();
    if (pthread_cond_init(&barrier->condition, NULL)) abort();
    barrier->arrived = 0;
    barrier->parties = parties;
    barrier->generation = 0;
}

static void barrier_wait(Barrier* barrier) {
    if (pthread_mutex_lock(&barrier->lock)) abort();
    int generation = barrier->generation;
    barrier->arrived++;
    if (barrier->arrived == barrier->parties) {
        barrier->arrived = 0;
        barrier->generation++;
        if (pthread_cond_broadcast(&barrier->condition)) abort();
    } else {
        while (generation == barrier->generation) {
            if (pthread_cond_wait(
                    &barrier->condition, &barrier->lock)) abort();
        }
    }
    if (pthread_mutex_unlock(&barrier->lock)) abort();
}

static void barrier_destroy(Barrier* barrier) {
    if (pthread_cond_destroy(&barrier->condition)) abort();
    if (pthread_mutex_destroy(&barrier->lock)) abort();
}

typedef struct Leaf {
    __btrc_arc_header arc;
} Leaf;

typedef struct External {
    __btrc_arc_header arc;
    __btrc_mutex_val_t* mutex;
} External;

typedef struct FailedRoot {
    __btrc_arc_header arc;
    External* external;
    int id;
} FailedRoot;

typedef struct ForestRoot {
    __btrc_arc_header arc;
    struct ForestRoot* peer;
    Leaf* shared;
} ForestRoot;

static const __btrc_arc_type leaf_type;
static const __btrc_arc_type external_type;
static const __btrc_arc_type failed_type;
static const __btrc_arc_type forest_type;
static _Atomic int leaf_destroys;
static _Atomic int external_destroys;
static _Atomic int failed_destroys;
static _Atomic int forest_destroys;
static _Atomic int contender_calls;
static _Atomic int contender_visitors;

static void* slot_access(
        volatile void* raw, void* expected,
        void* replacement, int commit) {
    void* volatile* slot = (void* volatile*)raw;
    void* current = *slot;
    if (commit && current == expected) *slot = replacement;
    return current;
}

static void initialize_header(
        __btrc_arc_header* header,
        const __btrc_arc_type* type) {
    memset(header, 0, sizeof(*header));
    header->rc = 1;
    header->type = type;
    header->state = __BTRC_ARC_LIVE;
}

static _Noreturn void unexpected_raise(const char* message) {
    fprintf(stderr, "unexpected ARC error: %s\n", message);
    abort();
}

static void leaf_destroy(void* raw) {
    atomic_fetch_add_explicit(&leaf_destroys, 1, memory_order_relaxed);
    free(raw);
}

static void external_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {
    External* external = (External*)raw;
    __btrc_mutex_val_visit(external->mutex, visit, context);
}

static void external_destroy(void* raw) {
    External* external = (External*)raw;
    __btrc_mutex_val_t* mutex = external->mutex;
    if (__btrc_arc_replace_edge(
            (volatile void*)mutex->value, slot_access,
            NULL, external, &leaf_type, 0)) abort();
    if (pthread_mutex_destroy(&mutex->lock)) abort();
    free(mutex->value);
    free(mutex);
    atomic_fetch_add_explicit(
        &external_destroys, 1, memory_order_relaxed);
    free(external);
}

static void failed_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {
    FailedRoot* root = (FailedRoot*)raw;
    if (root->id >= 100) {
        if (atomic_fetch_add_explicit(
                &contender_visitors, 1, memory_order_acq_rel) != 0) abort();
        if (atomic_load_explicit(
                &contender_calls, memory_order_acquire) != 2) abort();
        atomic_fetch_sub_explicit(
            &contender_visitors, 1, memory_order_acq_rel);
    }
    visit((volatile void*)&root->external,
        slot_access, &external_type, context);
}

static void failed_destroy(void* raw) {
    FailedRoot* root = (FailedRoot*)raw;
    if (root->external) abort();
    atomic_fetch_add_explicit(
        &failed_destroys, 1, memory_order_relaxed);
    free(root);
}

static void forest_visit(
        void* raw, __btrc_field_visit_fn visit, void* context) {
    ForestRoot* root = (ForestRoot*)raw;
    visit((volatile void*)&root->peer,
        slot_access, &forest_type, context);
    visit((volatile void*)&root->shared,
        slot_access, &leaf_type, context);
}

static void forest_destroy(void* raw) {
    ForestRoot* root = (ForestRoot*)raw;
    if (root->peer || root->shared) abort();
    atomic_fetch_add_explicit(
        &forest_destroys, 1, memory_order_relaxed);
    free(root);
}

static const __btrc_arc_type leaf_type = {
    .visit = NULL,
    .destroy = leaf_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = unexpected_raise,
};

static const __btrc_arc_type external_type = {
    .visit = external_visit,
    .destroy = external_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = unexpected_raise,
};

static const __btrc_arc_type failed_type = {
    .visit = failed_visit,
    .destroy = failed_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = unexpected_raise,
};

static const __btrc_arc_type forest_type = {
    .visit = forest_visit,
    .destroy = forest_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = unexpected_raise,
};

static Leaf* new_leaf(void) {
    Leaf* leaf = (Leaf*)__btrc_safe_calloc(1, sizeof(*leaf));
    initialize_header(&leaf->arc, &leaf_type);
    return leaf;
}

static External* new_external(Leaf* leaf) {
    External* external =
        (External*)__btrc_safe_calloc(1, sizeof(*external));
    initialize_header(&external->arc, &external_type);
    __btrc_mutex_val_t* mutex =
        (__btrc_mutex_val_t*)__btrc_safe_calloc(1, sizeof(*mutex));
    if (pthread_mutex_init(&mutex->lock, NULL)) abort();
    mutex->value = __btrc_safe_calloc(1, sizeof(void*));
    mutex->size = sizeof(void*);
    mutex->slot_access = slot_access;
    mutex->context = (void*)&leaf_type;
    mutex->owner = external;
    external->mutex = mutex;
    if (__btrc_arc_replace_edge(
            (volatile void*)mutex->value, slot_access,
            leaf, external, &leaf_type, 1)) abort();
    return external;
}

static FailedRoot* new_failed(int id) {
    FailedRoot* root =
        (FailedRoot*)__btrc_safe_calloc(1, sizeof(*root));
    initialize_header(&root->arc, &failed_type);
    root->id = id;
    return root;
}

static ForestRoot* new_forest_root(void) {
    ForestRoot* root =
        (ForestRoot*)__btrc_safe_calloc(1, sizeof(*root));
    initialize_header(&root->arc, &forest_type);
    return root;
}

static void attach_external(
        FailedRoot* root, External* external, int adopt) {
    if (__btrc_arc_replace_edge(
            (volatile void*)&root->external, slot_access,
            external, root, &external_type, adopt)) abort();
}

typedef struct MutexRace {
    External* external;
    _Atomic int locked;
} MutexRace;

static void* mutex_owner_worker(void* raw) {
    MutexRace* race = (MutexRace*)raw;
    void* volatile topology = __btrc_arc_topology_begin();
    if (pthread_mutex_lock(&race->external->mutex->lock)) abort();
    atomic_store_explicit(&race->locked, 1, memory_order_release);
    while (!atomic_load_explicit(
            &__btrc_arc_snapshot_pending, memory_order_acquire)) {
        sched_yield();
    }
    __btrc_arc_retain(race->external);
    if (pthread_mutex_unlock(&race->external->mutex->lock)) abort();
    __btrc_arc_topology_complete(&topology);
    return NULL;
}

static void test_mutex_lock_inversion(void) {
    Leaf* leaf = new_leaf();
    External* external = new_external(leaf);
    FailedRoot* failed = new_failed(1);
    attach_external(failed, external, 0);
    MutexRace race = {.external = external};
    pthread_t worker;
    if (pthread_create(&worker, NULL, mutex_owner_worker, &race)) abort();
    while (!atomic_load_explicit(&race.locked, memory_order_acquire)) {
        sched_yield();
    }
    __btrc_arc_abandon(failed);
    if (pthread_join(worker, NULL)) abort();
    if (atomic_load_explicit(&failed_destroys, memory_order_relaxed) != 1
            || atomic_load_explicit(
                &external_destroys, memory_order_relaxed) != 0
            || atomic_load_explicit(
                &leaf_destroys, memory_order_relaxed) != 0) abort();
    __btrc_arc_release(external, &external_type);
    __btrc_arc_release(external, &external_type);
    if (atomic_load_explicit(
            &external_destroys, memory_order_relaxed) != 1
            || atomic_load_explicit(
                &leaf_destroys, memory_order_relaxed) != 1) abort();
}

typedef struct Contender {
    Barrier* start;
    FailedRoot* root;
} Contender;

static void* contender_worker(void* raw) {
    Contender* contender = (Contender*)raw;
    atomic_fetch_add_explicit(
        &contender_calls, 1, memory_order_release);
    barrier_wait(contender->start);
    __btrc_arc_abandon(contender->root);
    return NULL;
}

static void test_snapshot_contenders(void) {
    Barrier start;
    barrier_init(&start, 2);
    atomic_store_explicit(&contender_calls, 0, memory_order_relaxed);
    Contender contenders[2] = {
        {.start = &start, .root = new_failed(100)},
        {.start = &start, .root = new_failed(101)},
    };
    pthread_t workers[2];
    for (int i = 0; i < 2; i++) {
        if (pthread_create(
                &workers[i], NULL, contender_worker, &contenders[i])) abort();
    }
    for (int i = 0; i < 2; i++) {
        if (pthread_join(workers[i], NULL)) abort();
    }
    barrier_destroy(&start);
    if (atomic_load_explicit(&contender_visitors, memory_order_relaxed) != 0
            || atomic_load_explicit(
                &failed_destroys, memory_order_relaxed) != 3) abort();
}

static void test_overlapping_queued_roots(void) {
    FailedRoot* outer = new_failed(2);
    External* inner = new_external(new_leaf());
    attach_external(outer, inner, 0);
    void* volatile topology = __btrc_arc_topology_begin();
    __btrc_arc_abandon(inner);
    __btrc_arc_abandon(outer);
    if (__btrc_abandon_count != 2) abort();
    __btrc_arc_topology_complete(&topology);
    if (__btrc_abandon_count != 0 || __btrc_abandon_queue
            || __btrc_abandon_drain_callback) abort();
    if (atomic_load_explicit(
            &failed_destroys, memory_order_relaxed) != 4
            || atomic_load_explicit(
                &external_destroys, memory_order_relaxed) != 2
            || atomic_load_explicit(
                &leaf_destroys, memory_order_relaxed) != 2) abort();
}

static void test_nested_queued_root_scc_with_shared_child(void) {
    ForestRoot* first = new_forest_root();
    ForestRoot* second = new_forest_root();
    Leaf* shared = new_leaf();
    if (__btrc_arc_replace_edge(
            (volatile void*)&first->peer, slot_access,
            second, first, &forest_type, 0)) abort();
    if (__btrc_arc_replace_edge(
            (volatile void*)&second->peer, slot_access,
            first, second, &forest_type, 0)) abort();
    if (__btrc_arc_replace_edge(
            (volatile void*)&first->shared, slot_access,
            shared, first, &leaf_type, 1)) abort();
    if (__btrc_arc_replace_edge(
            (volatile void*)&second->shared, slot_access,
            shared, second, &leaf_type, 0)) abort();

    void* volatile outer = __btrc_arc_topology_begin();
    void* volatile inner = __btrc_arc_topology_begin();
    __btrc_arc_abandon(second);
    __btrc_arc_abandon(first);
    if (__btrc_abandon_count != 2) abort();
    __btrc_arc_topology_complete(&inner);
    if (inner || __btrc_arc_topology_depth != 1
            || __btrc_abandon_count != 2) abort();
    __btrc_arc_topology_complete(&outer);
    if (outer || __btrc_arc_topology_depth != 0
            || __btrc_abandon_count != 0 || __btrc_abandon_queue
            || __btrc_abandon_drain_callback) abort();
    if (atomic_load_explicit(
            &forest_destroys, memory_order_relaxed) != 2
            || atomic_load_explicit(
                &leaf_destroys, memory_order_relaxed) != 3) abort();
}

int main(void) {
    test_mutex_lock_inversion();
    test_snapshot_contenders();
    test_overlapping_queued_roots();
    test_nested_queued_root_scc_with_shared_child();
    __btrc_cycle_state_cleanup();
    return 0;
}
