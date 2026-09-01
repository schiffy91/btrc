#include "btrc_background_jobs.h"

#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

enum {
    BTRC_BACKGROUND_JOBS_MAX_WORKERS = 16,
    BTRC_BACKGROUND_JOBS_MAX_CAPACITY = 4096,
};

typedef enum {
    JOB_SLOT_FREE = 0,
    JOB_SLOT_QUEUED = 1,
    JOB_SLOT_RUNNING = 2,
    JOB_SLOT_TERMINAL = 3,
} BtrcBackgroundJobSlotState;

typedef struct {
    BtrcBackgroundJobSlotState state;
    uint64_t sequence;
    uint64_t generation;
    atomic_bool cancellation;
    BtrcBackgroundJobRun run;
    void* context;
    BtrcBackgroundJobDispose dispose_context;
    int completion_kind;
} BtrcBackgroundJobSlot;

typedef struct {
    pthread_t owner;
    pthread_mutex_t lock;
    pthread_cond_t work_ready;
    bool lock_ready;
    bool condition_ready;
    bool accepting;
    bool closing;
    bool destroying;
    atomic_bool worker_failed;
    int close_mode;
    int created_workers;
    int capacity;
    int outstanding;
    pthread_t* workers;
    bool* joined;
    BtrcBackgroundJobSlot* slots;
    int* queue;
    int queue_head;
    int queue_count;
    int* completions;
    int completion_head;
    int completion_count;
    uint64_t next_sequence;
} BtrcBackgroundJobExecutor;

static bool on_owner(const BtrcBackgroundJobExecutor* executor) {
    return executor &&
        pthread_equal(executor->owner, pthread_self()) != 0;
}

static int ring_index(int head, int offset, int capacity) {
    int index = head + offset;
    if (index >= capacity) { index -= capacity; }
    return index;
}

static bool push_queue(BtrcBackgroundJobExecutor* executor, int slot) {
    if (!executor || executor->queue_count >= executor->capacity) {
        return false;
    }
    int tail = ring_index(
        executor->queue_head,
        executor->queue_count,
        executor->capacity);
    executor->queue[tail] = slot;
    executor->queue_count++;
    return true;
}

static int pop_queue(BtrcBackgroundJobExecutor* executor) {
    if (!executor || executor->queue_count <= 0) { return -1; }
    int slot = executor->queue[executor->queue_head];
    executor->queue_head = ring_index(
        executor->queue_head, 1, executor->capacity);
    executor->queue_count--;
    return slot;
}

static bool push_completion(
        BtrcBackgroundJobExecutor* executor, int slot) {
    if (!executor || executor->completion_count >= executor->capacity) {
        return false;
    }
    int tail = ring_index(
        executor->completion_head,
        executor->completion_count,
        executor->capacity);
    executor->completions[tail] = slot;
    executor->completion_count++;
    return true;
}

static int pop_completion(BtrcBackgroundJobExecutor* executor) {
    if (!executor || executor->completion_count <= 0) { return -1; }
    int slot = executor->completions[executor->completion_head];
    executor->completion_head = ring_index(
        executor->completion_head, 1, executor->capacity);
    executor->completion_count--;
    return slot;
}

static void request_all_cancellation(
        BtrcBackgroundJobExecutor* executor) {
    for (int index = 0; index < executor->capacity; ++index) {
        BtrcBackgroundJobSlot* slot = &executor->slots[index];
        if (slot->state == JOB_SLOT_QUEUED ||
            slot->state == JOB_SLOT_RUNNING) {
            atomic_store_explicit(
                &slot->cancellation, true, memory_order_release);
        }
    }
}

static void publish_terminal(
        BtrcBackgroundJobExecutor* executor,
        int slot_index,
        int completion_kind) {
    BtrcBackgroundJobSlot* slot = &executor->slots[slot_index];
    slot->completion_kind = completion_kind;
    slot->state = JOB_SLOT_TERMINAL;
    if (!push_completion(executor, slot_index)) {
        /* With capacity slots and no slot reuse before poll, the completion
         * ring cannot fill before every slot is terminal. Fail closed if an
         * invariant is violated rather than overwriting an owned context. */
        atomic_store_explicit(
            &executor->worker_failed, true, memory_order_release);
        executor->accepting = false;
        executor->closing = true;
        request_all_cancellation(executor);
        (void)pthread_cond_broadcast(&executor->work_ready);
    }
}

static void reset_slot(BtrcBackgroundJobSlot* slot) {
    if (!slot) { return; }
    slot->state = JOB_SLOT_FREE;
    slot->sequence = 0;
    slot->generation = 0;
    slot->run = NULL;
    slot->context = NULL;
    slot->dispose_context = NULL;
    slot->completion_kind = BTRC_BACKGROUND_JOB_FAILED;
    atomic_store_explicit(
        &slot->cancellation, false, memory_order_release);
}

static void* worker_main(void* opaque) {
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)opaque;
    for (;;) {
        if (pthread_mutex_lock(&executor->lock) != 0) {
            atomic_store_explicit(
                &executor->worker_failed, true, memory_order_release);
            return NULL;
        }
        while (executor->queue_count == 0 && !executor->closing) {
            int waited = pthread_cond_wait(
                &executor->work_ready, &executor->lock);
            if (waited != 0) {
                atomic_store_explicit(
                    &executor->worker_failed, true, memory_order_release);
                executor->accepting = false;
                executor->closing = true;
                request_all_cancellation(executor);
                (void)pthread_cond_broadcast(&executor->work_ready);
                (void)pthread_mutex_unlock(&executor->lock);
                return NULL;
            }
        }
        if (executor->queue_count == 0 && executor->closing) {
            (void)pthread_mutex_unlock(&executor->lock);
            return NULL;
        }

        int slot_index = pop_queue(executor);
        if (slot_index < 0 || slot_index >= executor->capacity) {
            atomic_store_explicit(
                &executor->worker_failed, true, memory_order_release);
            executor->accepting = false;
            executor->closing = true;
            request_all_cancellation(executor);
            (void)pthread_cond_broadcast(&executor->work_ready);
            (void)pthread_mutex_unlock(&executor->lock);
            return NULL;
        }
        BtrcBackgroundJobSlot* slot = &executor->slots[slot_index];
        if (slot->state != JOB_SLOT_QUEUED || !slot->run ||
            !slot->context || !slot->dispose_context) {
            atomic_store_explicit(
                &executor->worker_failed, true, memory_order_release);
            executor->accepting = false;
            executor->closing = true;
            request_all_cancellation(executor);
            (void)pthread_cond_broadcast(&executor->work_ready);
            (void)pthread_mutex_unlock(&executor->lock);
            return NULL;
        }
        slot->state = JOB_SLOT_RUNNING;
        bool cancelled_before_start = atomic_load_explicit(
            &slot->cancellation, memory_order_acquire);
        BtrcBackgroundJobRun run = slot->run;
        void* context = slot->context;
        void* cancellation = &slot->cancellation;
        (void)pthread_mutex_unlock(&executor->lock);

        int completion_kind = BTRC_BACKGROUND_JOB_CANCELLED;
        if (!cancelled_before_start) {
            completion_kind = run(context, cancellation);
            if (completion_kind != BTRC_BACKGROUND_JOB_COMPLETED &&
                completion_kind != BTRC_BACKGROUND_JOB_FAILED &&
                completion_kind != BTRC_BACKGROUND_JOB_CANCELLED) {
                completion_kind = BTRC_BACKGROUND_JOB_FAILED;
            }
        }

        if (pthread_mutex_lock(&executor->lock) != 0) {
            atomic_store_explicit(
                &executor->worker_failed, true, memory_order_release);
            return NULL;
        }
        publish_terminal(executor, slot_index, completion_kind);
        (void)pthread_mutex_unlock(&executor->lock);
    }
}

static void destroy_executor_storage(
        BtrcBackgroundJobExecutor* executor) {
    if (!executor) { return; }
    if (executor->condition_ready) {
        (void)pthread_cond_destroy(&executor->work_ready);
    }
    if (executor->lock_ready) {
        (void)pthread_mutex_destroy(&executor->lock);
    }
    free(executor->completions);
    free(executor->queue);
    free(executor->slots);
    free(executor->joined);
    free(executor->workers);
    free(executor);
}

static void stop_created_workers(
        BtrcBackgroundJobExecutor* executor) {
    if (!executor || !executor->lock_ready) { return; }
    if (pthread_mutex_lock(&executor->lock) == 0) {
        executor->accepting = false;
        executor->closing = true;
        request_all_cancellation(executor);
        if (executor->condition_ready) {
            (void)pthread_cond_broadcast(&executor->work_ready);
        }
        (void)pthread_mutex_unlock(&executor->lock);
    }
    for (int index = 0; index < executor->created_workers; ++index) {
        (void)pthread_join(executor->workers[index], NULL);
    }
}

int std_background_jobs_open(
        int worker_count,
        int capacity,
        void** executor_out) {
    if (!executor_out) { return BTRC_BACKGROUND_JOBS_OPEN_INVALID; }
    *executor_out = NULL;
    if (worker_count <= 0 ||
        worker_count > BTRC_BACKGROUND_JOBS_MAX_WORKERS ||
        capacity <= 0 || capacity > BTRC_BACKGROUND_JOBS_MAX_CAPACITY) {
        return BTRC_BACKGROUND_JOBS_OPEN_INVALID;
    }
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)calloc(
            1, sizeof(BtrcBackgroundJobExecutor));
    if (!executor) { return BTRC_BACKGROUND_JOBS_OPEN_OUT_OF_MEMORY; }
    executor->owner = pthread_self();
    executor->capacity = capacity;
    executor->accepting = true;
    executor->close_mode = -1;
    executor->next_sequence = UINT64_C(1);
    atomic_init(&executor->worker_failed, false);
    executor->workers = (pthread_t*)calloc(
        (size_t)worker_count, sizeof(pthread_t));
    executor->joined = (bool*)calloc((size_t)worker_count, sizeof(bool));
    executor->slots = (BtrcBackgroundJobSlot*)calloc(
        (size_t)capacity, sizeof(BtrcBackgroundJobSlot));
    executor->queue = (int*)calloc((size_t)capacity, sizeof(int));
    executor->completions = (int*)calloc((size_t)capacity, sizeof(int));
    if (!executor->workers || !executor->joined || !executor->slots ||
        !executor->queue || !executor->completions) {
        destroy_executor_storage(executor);
        return BTRC_BACKGROUND_JOBS_OPEN_OUT_OF_MEMORY;
    }
    for (int index = 0; index < capacity; ++index) {
        atomic_init(&executor->slots[index].cancellation, false);
    }
    if (pthread_mutex_init(&executor->lock, NULL) != 0) {
        destroy_executor_storage(executor);
        return BTRC_BACKGROUND_JOBS_OPEN_THREAD_FAILED;
    }
    executor->lock_ready = true;
    if (pthread_cond_init(&executor->work_ready, NULL) != 0) {
        destroy_executor_storage(executor);
        return BTRC_BACKGROUND_JOBS_OPEN_THREAD_FAILED;
    }
    executor->condition_ready = true;
    for (int index = 0; index < worker_count; ++index) {
        if (pthread_create(
                &executor->workers[index], NULL,
                worker_main, executor) != 0) {
            stop_created_workers(executor);
            destroy_executor_storage(executor);
            return BTRC_BACKGROUND_JOBS_OPEN_THREAD_FAILED;
        }
        executor->created_workers++;
    }
    *executor_out = executor;
    return BTRC_BACKGROUND_JOBS_OPENED;
}

int std_background_jobs_submit(
        void* executor_opaque,
        uint64_t generation,
        BtrcBackgroundJobRun run,
        void* context,
        BtrcBackgroundJobDispose dispose_context,
        uint64_t* sequence_out) {
    if (sequence_out) { *sequence_out = 0; }
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)executor_opaque;
    if (!executor || !sequence_out || generation == 0 || !run ||
        !context || !dispose_context) {
        return BTRC_BACKGROUND_JOB_SUBMIT_INVALID;
    }
    if (!on_owner(executor)) {
        return BTRC_BACKGROUND_JOB_SUBMIT_NOT_OWNER;
    }
    if (pthread_mutex_lock(&executor->lock) != 0) {
        return BTRC_BACKGROUND_JOB_SUBMIT_CLOSED;
    }
    if (!executor->accepting || executor->closing) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_SUBMIT_CLOSED;
    }
    if (executor->next_sequence == 0) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_TICKETS_EXHAUSTED;
    }
    int slot_index = -1;
    for (int index = 0; index < executor->capacity; ++index) {
        if (executor->slots[index].state == JOB_SLOT_FREE) {
            slot_index = index;
            break;
        }
    }
    if (slot_index < 0) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_QUEUE_FULL;
    }
    uint64_t sequence = executor->next_sequence;
    executor->next_sequence = sequence == UINT64_MAX
        ? 0 : sequence + UINT64_C(1);
    BtrcBackgroundJobSlot* slot = &executor->slots[slot_index];
    slot->state = JOB_SLOT_QUEUED;
    slot->sequence = sequence;
    slot->generation = generation;
    slot->run = run;
    slot->context = context;
    slot->dispose_context = dispose_context;
    slot->completion_kind = BTRC_BACKGROUND_JOB_FAILED;
    atomic_store_explicit(
        &slot->cancellation, false, memory_order_release);
    if (!push_queue(executor, slot_index)) {
        reset_slot(slot);
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_QUEUE_FULL;
    }
    executor->outstanding++;
    *sequence_out = sequence;
    (void)pthread_cond_signal(&executor->work_ready);
    (void)pthread_mutex_unlock(&executor->lock);
    return BTRC_BACKGROUND_JOB_SUBMITTED;
}

int std_background_jobs_cancel(
        void* executor_opaque,
        uint64_t sequence,
        uint64_t generation) {
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)executor_opaque;
    if (!executor || sequence == 0 || generation == 0) {
        return BTRC_BACKGROUND_JOB_CANCEL_STALE;
    }
    if (!on_owner(executor)) {
        return BTRC_BACKGROUND_JOB_CANCEL_NOT_OWNER;
    }
    if (pthread_mutex_lock(&executor->lock) != 0) {
        return BTRC_BACKGROUND_JOB_CANCEL_CLOSED;
    }
    if (!executor->accepting || executor->closing) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_CANCEL_CLOSED;
    }
    int result = BTRC_BACKGROUND_JOB_CANCEL_STALE;
    for (int index = 0; index < executor->capacity; ++index) {
        BtrcBackgroundJobSlot* slot = &executor->slots[index];
        if (slot->sequence != sequence || slot->generation != generation ||
            slot->state == JOB_SLOT_FREE) {
            continue;
        }
        if (slot->state == JOB_SLOT_TERMINAL) {
            result = BTRC_BACKGROUND_JOB_ALREADY_TERMINAL;
        } else {
            atomic_store_explicit(
                &slot->cancellation, true, memory_order_release);
            result = BTRC_BACKGROUND_JOB_CANCEL_REQUESTED;
        }
        break;
    }
    (void)pthread_mutex_unlock(&executor->lock);
    return result;
}

int std_background_jobs_cancel_generation(
        void* executor_opaque,
        uint64_t generation,
        int* requested_out) {
    if (requested_out) { *requested_out = 0; }
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)executor_opaque;
    if (!executor || !requested_out || generation == 0) {
        return BTRC_BACKGROUND_JOB_CANCEL_STALE;
    }
    if (!on_owner(executor)) {
        return BTRC_BACKGROUND_JOB_CANCEL_NOT_OWNER;
    }
    if (pthread_mutex_lock(&executor->lock) != 0) {
        return BTRC_BACKGROUND_JOB_CANCEL_CLOSED;
    }
    if (!executor->accepting || executor->closing) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_CANCEL_CLOSED;
    }
    int requested = 0;
    for (int index = 0; index < executor->capacity; ++index) {
        BtrcBackgroundJobSlot* slot = &executor->slots[index];
        if (slot->generation == generation &&
            (slot->state == JOB_SLOT_QUEUED ||
             slot->state == JOB_SLOT_RUNNING)) {
            atomic_store_explicit(
                &slot->cancellation, true, memory_order_release);
            requested++;
        }
    }
    *requested_out = requested;
    (void)pthread_mutex_unlock(&executor->lock);
    return BTRC_BACKGROUND_JOB_CANCEL_REQUESTED;
}

int std_background_jobs_poll(
        void* executor_opaque,
        BtrcBackgroundJobNativeCompletion* completion_out) {
    if (completion_out) {
        completion_out->kind = BTRC_BACKGROUND_JOB_FAILED;
        completion_out->sequence = 0;
        completion_out->generation = 0;
        completion_out->context = NULL;
        completion_out->dispose_context = NULL;
    }
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)executor_opaque;
    if (!executor || !completion_out) {
        return BTRC_BACKGROUND_JOB_POLL_CLOSED;
    }
    if (!on_owner(executor)) {
        return BTRC_BACKGROUND_JOB_POLL_NOT_OWNER;
    }
    int locked = pthread_mutex_trylock(&executor->lock);
    if (locked == EBUSY) {
        return BTRC_BACKGROUND_JOB_POLL_BUSY;
    }
    if (locked != 0) {
        return BTRC_BACKGROUND_JOB_POLL_CLOSED;
    }
    int slot_index = pop_completion(executor);
    if (slot_index < 0) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_POLL_EMPTY;
    }
    BtrcBackgroundJobSlot* slot = &executor->slots[slot_index];
    if (slot->state != JOB_SLOT_TERMINAL || !slot->context ||
        !slot->dispose_context) {
        atomic_store_explicit(
            &executor->worker_failed, true, memory_order_release);
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOB_POLL_CLOSED;
    }
    completion_out->kind = slot->completion_kind;
    completion_out->sequence = slot->sequence;
    completion_out->generation = slot->generation;
    completion_out->context = slot->context;
    completion_out->dispose_context = slot->dispose_context;
    reset_slot(slot);
    executor->outstanding--;
    (void)pthread_mutex_unlock(&executor->lock);
    return BTRC_BACKGROUND_JOB_POLL_READY;
}

int std_background_jobs_outstanding(void* executor_opaque) {
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)executor_opaque;
    if (!executor || !on_owner(executor)) { return -1; }
    if (pthread_mutex_lock(&executor->lock) != 0) { return -1; }
    int result = executor->outstanding;
    (void)pthread_mutex_unlock(&executor->lock);
    return result;
}

int std_background_jobs_cancel_requested(
        void* cancellation) {
    atomic_bool* requested = (atomic_bool*)cancellation;
    return requested && atomic_load_explicit(
        requested, memory_order_acquire) ? 1 : 0;
}

static void dispose_slots(
        BtrcBackgroundJobExecutor* executor,
        int* completed_out,
        int* failed_out,
        int* cancelled_out,
        int* disposed_out) {
    for (int index = 0; index < executor->capacity; ++index) {
        BtrcBackgroundJobSlot* slot = &executor->slots[index];
        if (slot->state == JOB_SLOT_FREE) { continue; }
        if (slot->state == JOB_SLOT_TERMINAL) {
            if (slot->completion_kind == BTRC_BACKGROUND_JOB_COMPLETED) {
                (*completed_out)++;
            } else if (slot->completion_kind == BTRC_BACKGROUND_JOB_CANCELLED) {
                (*cancelled_out)++;
            } else {
                (*failed_out)++;
            }
        } else {
            (*cancelled_out)++;
        }
        void* context = slot->context;
        BtrcBackgroundJobDispose dispose_context = slot->dispose_context;
        slot->state = JOB_SLOT_FREE;
        slot->context = NULL;
        slot->dispose_context = NULL;
        if (context && dispose_context) {
            dispose_context(context);
            (*disposed_out)++;
        }
    }
}

int std_background_jobs_close(
        void* executor_opaque,
        int mode,
        int* completed_out,
        int* failed_out,
        int* cancelled_out,
        int* disposed_out) {
    if (completed_out) { *completed_out = 0; }
    if (failed_out) { *failed_out = 0; }
    if (cancelled_out) { *cancelled_out = 0; }
    if (disposed_out) { *disposed_out = 0; }
    BtrcBackgroundJobExecutor* executor =
        (BtrcBackgroundJobExecutor*)executor_opaque;
    if (!executor) { return BTRC_BACKGROUND_JOBS_ALREADY_CLOSED; }
    if (!completed_out || !failed_out || !cancelled_out || !disposed_out) {
        return BTRC_BACKGROUND_JOBS_CLOSE_INVALID_MODE;
    }
    if (mode != BTRC_BACKGROUND_JOBS_DRAIN &&
        mode != BTRC_BACKGROUND_JOBS_CANCEL_PENDING) {
        return BTRC_BACKGROUND_JOBS_CLOSE_INVALID_MODE;
    }
    if (!on_owner(executor)) {
        return BTRC_BACKGROUND_JOBS_CLOSE_NOT_OWNER;
    }
    if (pthread_mutex_lock(&executor->lock) != 0) {
        return BTRC_BACKGROUND_JOBS_CLOSE_SYNC_FAILED;
    }
    if (executor->destroying) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOBS_CLOSE_SYNC_FAILED;
    }
    if (!executor->closing || executor->close_mode < 0) {
        executor->accepting = false;
        executor->closing = true;
        executor->close_mode = mode;
        if (mode == BTRC_BACKGROUND_JOBS_CANCEL_PENDING) {
            request_all_cancellation(executor);
        }
        (void)pthread_cond_broadcast(&executor->work_ready);
    } else if (executor->close_mode != mode) {
        (void)pthread_mutex_unlock(&executor->lock);
        return BTRC_BACKGROUND_JOBS_CLOSE_INVALID_MODE;
    }
    (void)pthread_mutex_unlock(&executor->lock);

    bool join_failed = false;
    for (int index = 0; index < executor->created_workers; ++index) {
        if (executor->joined[index]) { continue; }
        int joined = pthread_join(executor->workers[index], NULL);
        if (joined == 0) {
            executor->joined[index] = true;
        } else {
            join_failed = true;
        }
    }
    if (join_failed) { return BTRC_BACKGROUND_JOBS_CLOSE_JOIN_FAILED; }

    if (pthread_mutex_lock(&executor->lock) != 0) {
        return BTRC_BACKGROUND_JOBS_CLOSE_SYNC_FAILED;
    }
    executor->destroying = true;
    executor->queue_head = 0;
    executor->queue_count = 0;
    executor->completion_head = 0;
    executor->completion_count = 0;
    executor->outstanding = 0;
    (void)pthread_mutex_unlock(&executor->lock);

    dispose_slots(
        executor,
        completed_out,
        failed_out,
        cancelled_out,
        disposed_out);
    bool worker_failed = atomic_load_explicit(
        &executor->worker_failed, memory_order_acquire);
    destroy_executor_storage(executor);
    return worker_failed
        ? BTRC_BACKGROUND_JOBS_CLOSE_WORKER_FAILED
        : BTRC_BACKGROUND_JOBS_CLOSED;
}
