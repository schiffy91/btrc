#include "btrc_gpu_compute_singleton.h"

#include <stdio.h>

static void* destroyed_candidate = NULL;

static void record_destroy(void* candidate) {
    destroyed_candidate = candidate;
}

int main(void) {
    _Atomic(void*) singleton = NULL;
    int winner = 1;
    int loser = 2;

    void* published = btrc_gpu_publish_compute_candidate(
        &singleton, &winner, record_destroy);
    if (published != &winner ||
        atomic_load_explicit(&singleton, memory_order_acquire) != &winner ||
        destroyed_candidate != NULL) {
        fputs("FAIL: initial candidate was not published\n", stderr);
        return 1;
    }

    published = btrc_gpu_publish_compute_candidate(
        &singleton, &loser, record_destroy);
    if (published != &winner ||
        atomic_load_explicit(&singleton, memory_order_acquire) != &winner ||
        destroyed_candidate != &loser) {
        fputs("FAIL: losing candidate was not destroyed\n", stderr);
        return 1;
    }

    return 0;
}
