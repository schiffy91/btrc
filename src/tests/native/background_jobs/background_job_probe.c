#include "background_job_probe.h"

#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>

enum { JOB_PROBE_CAPACITY = 32 };

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

void job_probe_mark_started(int identity) {
    if (!valid_identity(identity)) { return; }
    atomic_fetch_add_explicit(&runs[identity], 1, memory_order_acq_rel);
    atomic_store_explicit(&started[identity], 1, memory_order_release);
}

void job_probe_mark_finished(int identity) {
    if (!valid_identity(identity)) { return; }
    atomic_store_explicit(&finished[identity], 1, memory_order_release);
}

void job_probe_record_disposal(int identity) {
    if (valid_identity(identity)) {
        atomic_fetch_add_explicit(
            &disposals[identity], 1, memory_order_acq_rel);
    }
}

void job_probe_release(void) {
    atomic_store_explicit(&released, true, memory_order_release);
}

int job_probe_released(void) {
    return atomic_load_explicit(&released, memory_order_acquire) ? 1 : 0;
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

void job_probe_yield(void) {
    (void)sched_yield();
}
