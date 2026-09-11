/* Thread-safe ownership transfer for deferred GPU callback records. */
#ifndef BTRC_GPU_PENDING_LIST_H
#define BTRC_GPU_PENDING_LIST_H

#include <stdbool.h>
#include <stddef.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#endif

typedef struct BtrcGPUPendingLink BtrcGPUPendingLink;

struct BtrcGPUPendingLink {
    BtrcGPUPendingLink* next;
};

typedef struct {
#ifdef _WIN32
    CRITICAL_SECTION lock;
#else
    pthread_mutex_t lock;
#endif
    BtrcGPUPendingLink* head;
    bool lock_initialized;
} BtrcGPUPendingList;

/* Initialization and destruction require exclusive lifetime ownership. All
 * producers and reapers must stop, and the list must be drained, before
 * destroy. The destroy operation is idempotent for serial cleanup paths. */
static inline bool btrc_gpu_pending_list_init(BtrcGPUPendingList* list) {
    if (!list) { return false; }
    list->head = NULL;
    list->lock_initialized = false;
#ifdef _WIN32
    InitializeCriticalSection(&list->lock);
#else
    if (pthread_mutex_init(&list->lock, NULL) != 0) { return false; }
#endif
    list->lock_initialized = true;
    return true;
}

static inline bool btrc_gpu_pending_list_destroy(BtrcGPUPendingList* list) {
    if (!list || !list->lock_initialized) { return true; }
    if (list->head) { return false; }
#ifdef _WIN32
    DeleteCriticalSection(&list->lock);
#else
    if (pthread_mutex_destroy(&list->lock) != 0) { return false; }
#endif
    list->lock_initialized = false;
    return true;
}

static inline void btrc_gpu_pending_list_lock(BtrcGPUPendingList* list) {
#ifdef _WIN32
    EnterCriticalSection(&list->lock);
#else
    (void)pthread_mutex_lock(&list->lock);
#endif
}

static inline void btrc_gpu_pending_list_unlock(BtrcGPUPendingList* list) {
#ifdef _WIN32
    LeaveCriticalSection(&list->lock);
#else
    (void)pthread_mutex_unlock(&list->lock);
#endif
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
