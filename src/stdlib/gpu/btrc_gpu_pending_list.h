/* Thread-safe ownership transfer for deferred GPU callback records. */
#ifndef BTRC_GPU_PENDING_LIST_H
#define BTRC_GPU_PENDING_LIST_H

#include <stdbool.h>
#include <stdatomic.h>

typedef struct BtrcGPUPendingLink BtrcGPUPendingLink;

struct BtrcGPUPendingLink {
    BtrcGPUPendingLink* next;
};

typedef struct {
    atomic_bool locked;
    BtrcGPUPendingLink* head;
} BtrcGPUPendingList;

static inline void btrc_gpu_pending_list_init(BtrcGPUPendingList* list) {
    atomic_init(&list->locked, false);
    list->head = NULL;
}

static inline void btrc_gpu_pending_list_lock(BtrcGPUPendingList* list) {
    bool expected = false;
    while (!atomic_compare_exchange_weak_explicit(
            &list->locked, &expected, true,
            memory_order_acquire, memory_order_relaxed)) {
        expected = false;
    }
}

static inline void btrc_gpu_pending_list_unlock(BtrcGPUPendingList* list) {
    atomic_store_explicit(&list->locked, false, memory_order_release);
}

static inline void btrc_gpu_pending_list_prepend(
        BtrcGPUPendingList* list, BtrcGPUPendingLink* link) {
    btrc_gpu_pending_list_lock(list);
    link->next = list->head;
    list->head = link;
    btrc_gpu_pending_list_unlock(list);
}

static inline BtrcGPUPendingLink* btrc_gpu_pending_list_take_all(
        BtrcGPUPendingList* list) {
    btrc_gpu_pending_list_lock(list);
    BtrcGPUPendingLink* head = list->head;
    list->head = NULL;
    btrc_gpu_pending_list_unlock(list);
    return head;
}

/* `links` is privately owned by the caller. Find its tail without holding the
 * shared lock, then return the whole batch in one short critical section. */
static inline void btrc_gpu_pending_list_merge(
        BtrcGPUPendingList* list, BtrcGPUPendingLink* links) {
    if (!links) { return; }
    BtrcGPUPendingLink* tail = links;
    while (tail->next) { tail = tail->next; }
    btrc_gpu_pending_list_lock(list);
    tail->next = list->head;
    list->head = links;
    btrc_gpu_pending_list_unlock(list);
}

#endif /* BTRC_GPU_PENDING_LIST_H */
