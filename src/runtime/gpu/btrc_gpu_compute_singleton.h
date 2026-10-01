#ifndef BTRC_GPU_COMPUTE_SINGLETON_H
#define BTRC_GPU_COMPUTE_SINGLETON_H

#include <stddef.h>
#include <stdatomic.h>

typedef void (*btrc_gpu_destroy_compute_candidate_fn)(void* candidate);

static inline void* btrc_gpu_publish_compute_candidate(
    _Atomic(void*)* singleton,
    void* candidate,
    btrc_gpu_destroy_compute_candidate_fn destroy_candidate) {
    void* expected = NULL;
    if (atomic_compare_exchange_strong_explicit(
            singleton, &expected, candidate,
            memory_order_release, memory_order_acquire)) {
        return candidate;
    }
    destroy_candidate(candidate);
    return expected;
}

#endif /* BTRC_GPU_COMPUTE_SINGLETON_H */
