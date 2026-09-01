#ifndef BTRC_BACKGROUND_JOBS_H
#define BTRC_BACKGROUND_JOBS_H

#include <stdatomic.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    BTRC_BACKGROUND_JOBS_OPENED = 0,
    BTRC_BACKGROUND_JOBS_OPEN_INVALID = 1,
    BTRC_BACKGROUND_JOBS_OPEN_OUT_OF_MEMORY = 2,
    BTRC_BACKGROUND_JOBS_OPEN_THREAD_FAILED = 3,
};

enum {
    BTRC_BACKGROUND_JOB_SUBMITTED = 0,
    BTRC_BACKGROUND_JOB_QUEUE_FULL = 1,
    BTRC_BACKGROUND_JOB_SUBMIT_CLOSED = 2,
    BTRC_BACKGROUND_JOB_SUBMIT_INVALID = 3,
    BTRC_BACKGROUND_JOB_SUBMIT_NOT_OWNER = 4,
    BTRC_BACKGROUND_JOB_TICKETS_EXHAUSTED = 5,
};

enum {
    BTRC_BACKGROUND_JOB_CANCEL_REQUESTED = 0,
    BTRC_BACKGROUND_JOB_ALREADY_TERMINAL = 1,
    BTRC_BACKGROUND_JOB_CANCEL_STALE = 2,
    BTRC_BACKGROUND_JOB_CANCEL_CLOSED = 3,
    BTRC_BACKGROUND_JOB_CANCEL_NOT_OWNER = 4,
};

enum {
    BTRC_BACKGROUND_JOB_POLL_READY = 0,
    BTRC_BACKGROUND_JOB_POLL_EMPTY = 1,
    BTRC_BACKGROUND_JOB_POLL_CLOSED = 2,
    BTRC_BACKGROUND_JOB_POLL_NOT_OWNER = 3,
    BTRC_BACKGROUND_JOB_POLL_BUSY = 4,
};

enum {
    BTRC_BACKGROUND_JOB_COMPLETED = 0,
    BTRC_BACKGROUND_JOB_FAILED = 1,
    BTRC_BACKGROUND_JOB_CANCELLED = 2,
};

enum {
    BTRC_BACKGROUND_JOBS_DRAIN = 0,
    BTRC_BACKGROUND_JOBS_CANCEL_PENDING = 1,
};

enum {
    BTRC_BACKGROUND_JOBS_CLOSED = 0,
    BTRC_BACKGROUND_JOBS_ALREADY_CLOSED = 1,
    BTRC_BACKGROUND_JOBS_CLOSE_NOT_OWNER = 2,
    BTRC_BACKGROUND_JOBS_CLOSE_INVALID_MODE = 3,
    BTRC_BACKGROUND_JOBS_CLOSE_JOIN_FAILED = 4,
    BTRC_BACKGROUND_JOBS_CLOSE_WORKER_FAILED = 5,
    BTRC_BACKGROUND_JOBS_CLOSE_SYNC_FAILED = 6,
};

typedef int (*BtrcBackgroundJobRun)(
    void* context, void* cancellation);
typedef void (*BtrcBackgroundJobDispose)(void* context);

typedef struct BtrcBackgroundJobNativeCompletion {
    int kind;
    uint64_t sequence;
    uint64_t generation;
    void* context;
    BtrcBackgroundJobDispose dispose_context;
} BtrcBackgroundJobNativeCompletion;

int std_background_jobs_open(
    int worker_count,
    int capacity,
    void** executor_out);

int std_background_jobs_submit(
    void* executor,
    uint64_t generation,
    BtrcBackgroundJobRun run,
    void* context,
    BtrcBackgroundJobDispose dispose_context,
    uint64_t* sequence_out);

int std_background_jobs_cancel(
    void* executor,
    uint64_t sequence,
    uint64_t generation);

int std_background_jobs_cancel_generation(
    void* executor,
    uint64_t generation,
    int* requested_out);

int std_background_jobs_poll(
    void* executor,
    BtrcBackgroundJobNativeCompletion* completion_out);

int std_background_jobs_outstanding(void* executor);

int std_background_jobs_cancel_requested(
    void* cancellation);

int std_background_jobs_close(
    void* executor,
    int mode,
    int* completed_out,
    int* failed_out,
    int* cancelled_out,
    int* disposed_out);

#ifdef __cplusplus
}
#endif

#endif
