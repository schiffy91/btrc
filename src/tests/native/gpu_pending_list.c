#include "btrc_gpu_pending_list.h"

#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdlib.h>

enum {
    PRODUCER_COUNT = 4,
    NODES_PER_PRODUCER = 2000,
    NODE_COUNT = PRODUCER_COUNT * NODES_PER_PRODUCER,
};

typedef struct {
    BtrcGPUPendingLink link;
    unsigned int id;
    bool retried;
} TestNode;

typedef struct {
    BtrcGPUPendingList* list;
    unsigned int producer;
} Producer;

static atomic_uint producers_done;
static atomic_uint nodes_released;

static void* produce(void* raw) {
    Producer* producer = (Producer*)raw;
    for (unsigned int index = 0; index < NODES_PER_PRODUCER; index++) {
        TestNode* node = (TestNode*)calloc(1, sizeof(TestNode));
        assert(node != NULL);
        node->id = producer->producer * NODES_PER_PRODUCER + index;
        btrc_gpu_pending_list_prepend(producer->list, &node->link);
    }
    atomic_fetch_add_explicit(&producers_done, 1, memory_order_release);
    return NULL;
}

static void process_batch(
        BtrcGPUPendingList* list, BtrcGPUPendingLink* links) {
    BtrcGPUPendingLink* retry = NULL;
    while (links) {
        BtrcGPUPendingLink* next = links->next;
        TestNode* node = (TestNode*)links;
        if (!node->retried && (node->id & 1u) == 0) {
            node->retried = true;
            links->next = retry;
            retry = links;
        } else {
            free(node);
            atomic_fetch_add_explicit(
                &nodes_released, 1, memory_order_relaxed);
        }
        links = next;
    }
    btrc_gpu_pending_list_merge(list, retry);
}

static void* reap(void* raw) {
    BtrcGPUPendingList* list = (BtrcGPUPendingList*)raw;
    while (atomic_load_explicit(
               &nodes_released, memory_order_acquire) < NODE_COUNT) {
        BtrcGPUPendingLink* links =
            btrc_gpu_pending_list_take_all(list);
        if (links) {
            process_batch(list, links);
        } else {
            sched_yield();
        }
    }
    return NULL;
}

int main(void) {
    BtrcGPUPendingList list;
    btrc_gpu_pending_list_init(&list);
    atomic_init(&producers_done, 0);
    atomic_init(&nodes_released, 0);

    pthread_t producers[PRODUCER_COUNT];
    Producer contexts[PRODUCER_COUNT];
    pthread_t reaper;
    assert(pthread_create(&reaper, NULL, reap, &list) == 0);
    for (unsigned int index = 0; index < PRODUCER_COUNT; index++) {
        contexts[index] = (Producer){ .list = &list, .producer = index };
        assert(pthread_create(
                   &producers[index], NULL, produce, &contexts[index]) == 0);
    }
    for (unsigned int index = 0; index < PRODUCER_COUNT; index++) {
        assert(pthread_join(producers[index], NULL) == 0);
    }
    assert(atomic_load_explicit(
               &producers_done, memory_order_acquire) == PRODUCER_COUNT);
    assert(pthread_join(reaper, NULL) == 0);
    assert(atomic_load_explicit(
               &nodes_released, memory_order_relaxed) == NODE_COUNT);
    assert(btrc_gpu_pending_list_take_all(&list) == NULL);
    return 0;
}
