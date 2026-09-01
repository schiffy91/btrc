#include "background_job_probe.h"

#include "btrc_background_jobs.h"

#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdlib.h>

enum { JOB_PROBE_CAPACITY = 32 };

typedef struct {
    int identity;
    int behavior;
} JobProbe;

static atomic_bool released;
static atomic_int started[JOB_PROBE_CAPACITY];
static atomic_int finished[JOB_PROBE_CAPACITY];
static atomic_int runs[JOB_PROBE_CAPACITY];
static atomic_int disposals[JOB_PROBE_CAPACITY];

static bool valid_identity(int identity) {
    return identity >= 0 && identity < JOB_PROBE_CAPACITY;
}

void job_probe_reset(void) {
    atomic_store_explicit(&released, false, memory_order_release);
    for (int index = 0; index < JOB_PROBE_CAPACITY; ++index) {
        atomic_store_explicit(&started[index], 0, memory_order_release);
        atomic_store_explicit(&finished[index], 0, memory_order_release);
        atomic_store_explicit(&runs[index], 0, memory_order_release);
        atomic_store_explicit(&disposals[index], 0, memory_order_release);
    }
}

void* job_probe_create(int identity, int behavior) {
    if (!valid_identity(identity) || behavior < JOB_PROBE_COMPLETE ||
        behavior > JOB_PROBE_FAIL) {
        return NULL;
    }
    JobProbe* probe = (JobProbe*)calloc(1, sizeof(JobProbe));
    if (!probe) { return NULL; }
    probe->identity = identity;
    probe->behavior = behavior;
    return probe;
}

int job_probe_run(void* context, void* cancellation) {
    JobProbe* probe = (JobProbe*)context;
    if (!probe || !valid_identity(probe->identity)) {
        return BTRC_BACKGROUND_JOB_FAILED;
    }
    int identity = probe->identity;
    atomic_fetch_add_explicit(&runs[identity], 1, memory_order_acq_rel);
    atomic_store_explicit(&started[identity], 1, memory_order_release);
    int result = BTRC_BACKGROUND_JOB_COMPLETED;
    if (probe->behavior == JOB_PROBE_HOLD) {
        while (!atomic_load_explicit(&released, memory_order_acquire)) {
            (void)sched_yield();
        }
    } else if (probe->behavior == JOB_PROBE_CANCEL) {
        while (!std_background_jobs_cancel_requested(cancellation)) {
            (void)sched_yield();
        }
        result = BTRC_BACKGROUND_JOB_CANCELLED;
    } else if (probe->behavior == JOB_PROBE_FAIL) {
        result = BTRC_BACKGROUND_JOB_FAILED;
    }
    atomic_store_explicit(&finished[identity], 1, memory_order_release);
    return result;
}

void job_probe_dispose(void* context) {
    JobProbe* probe = (JobProbe*)context;
    if (!probe) { return; }
    if (valid_identity(probe->identity)) {
        atomic_fetch_add_explicit(
            &disposals[probe->identity], 1, memory_order_acq_rel);
    }
    free(probe);
}

void job_probe_release(void) {
    atomic_store_explicit(&released, true, memory_order_release);
}

int job_probe_started(int identity) {
    return valid_identity(identity)
        ? atomic_load_explicit(&started[identity], memory_order_acquire) : 0;
}

int job_probe_finished(int identity) {
    return valid_identity(identity)
        ? atomic_load_explicit(&finished[identity], memory_order_acquire) : 0;
}

int job_probe_runs(int identity) {
    return valid_identity(identity)
        ? atomic_load_explicit(&runs[identity], memory_order_acquire) : 0;
}

int job_probe_disposals(int identity) {
    return valid_identity(identity)
        ? atomic_load_explicit(&disposals[identity], memory_order_acquire) : 0;
}

int job_probe_identity(void* context) {
    JobProbe* probe = (JobProbe*)context;
    return probe ? probe->identity : -1;
}

void job_probe_yield(void) {
    (void)sched_yield();
}
