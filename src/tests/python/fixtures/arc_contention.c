#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <time.h>

/* BTRC_RUNTIME_HELPERS */

typedef struct {
    __btrc_arc_header arc;
} Item;

static atomic_int ready = 0;
static atomic_int started = 0;
static atomic_int stopped = 0;
static atomic_int destroyed = 0;

static void destroy_item(void* item) {
    atomic_fetch_add_explicit(&destroyed, 1, memory_order_relaxed);
    free(item);
}

static const __btrc_arc_type item_type = {
    .destroy = destroy_item,
};

static Item* new_item(void) {
    Item* item = (Item*)calloc(1, sizeof(Item));
    assert(item);
    item->arc.rc = 1;
    item->arc.state = __BTRC_ARC_LIVE;
    item->arc.type = &item_type;
    return item;
}

/* Independent objects deliberately still contend on the runtime lock, as
 * foreground layout and background archive decoding do in one process. */
static void work(Item* item) {
    for (int index = 0; index < 500; index++) {
        __btrc_arc_retain(item);
        __btrc_arc_release_acyclic(item, &item_type);
    }
}

typedef struct {
    unsigned long batches;
} Worker;

static void* background(void* raw) {
    Worker* worker = (Worker*)raw;
    Item* item = new_item();
    atomic_fetch_add_explicit(&ready, 1, memory_order_release);
    while (!atomic_load_explicit(&started, memory_order_acquire)) {}
    do {
        work(item);
        worker->batches++;
    } while (!atomic_load_explicit(&stopped, memory_order_acquire));
    __btrc_arc_release_acyclic(item, &item_type);
    return NULL;
}

static double now(void) {
    struct timespec value;
    assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

int main(int argc, char** argv) {
    int count = argc > 1 ? atoi(argv[1]) : 2;
    assert(count == 0 || count == 2);
    pthread_t threads[2];
    Worker workers[2] = {{0}, {0}};
    for (int index = 0; index < count; index++) {
        assert(pthread_create(&threads[index], NULL, background, &workers[index]) == 0);
    }
    while (atomic_load_explicit(&ready, memory_order_acquire) != count) {}
    Item* foreground = new_item();
    atomic_store_explicit(&started, 1, memory_order_release);
    double samples[200];
    double start = now();
    for (int index = 0; index < 200; index++) {
        double before = now();
        work(foreground);
        samples[index] = (now() - before) * 1000.0;
    }
    double elapsed = (now() - start) * 1000.0;
    atomic_store_explicit(&stopped, 1, memory_order_release);
    for (int index = 0; index < count; index++) {
        assert(pthread_join(threads[index], NULL) == 0);
        assert(workers[index].batches > 0);
    }
    __btrc_arc_release_acyclic(foreground, &item_type);
    assert(atomic_load_explicit(&destroyed, memory_order_relaxed) == count + 1);
    for (int index = 0; index < 200; index++) {
        printf("batch,%d,%.6f\n", index, samples[index]);
    }
    printf("total,%d,%.6f,%lu\n", count, elapsed, workers[0].batches + workers[1].batches);
    return 0;
}
