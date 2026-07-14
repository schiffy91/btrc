#ifdef malloc
#undef malloc
#endif
#ifdef calloc
#undef calloc
#endif
#ifdef realloc
#undef realloc
#endif
#ifdef free
#undef free
#endif

#include <pthread.h>
#include <stddef.h>
#include <stdlib.h>

#define BTRC_TEST_MAX_ALLOCATIONS 32768

static pthread_mutex_t allocation_lock = PTHREAD_MUTEX_INITIALIZER;
static void* allocations[BTRC_TEST_MAX_ALLOCATIONS];
static long allocation_count;
static long allocation_checkpoint;

void btrc_test_free(void* pointer);

static int allocation_index(void* pointer) {
    for (int index = 0; index < BTRC_TEST_MAX_ALLOCATIONS; index++) {
        if (allocations[index] == pointer) return index;
    }
    return -1;
}

static void record_allocation(void* pointer) {
    if (!pointer) return;
    for (int index = 0; index < BTRC_TEST_MAX_ALLOCATIONS; index++) {
        if (allocations[index]) continue;
        allocations[index] = pointer;
        allocation_count++;
        return;
    }
    abort();
}

void* btrc_test_malloc(size_t size) {
    void* pointer = malloc(size);
    (void)pthread_mutex_lock(&allocation_lock);
    record_allocation(pointer);
    (void)pthread_mutex_unlock(&allocation_lock);
    return pointer;
}

void* btrc_test_calloc(size_t count, size_t size) {
    void* pointer = calloc(count, size);
    (void)pthread_mutex_lock(&allocation_lock);
    record_allocation(pointer);
    (void)pthread_mutex_unlock(&allocation_lock);
    return pointer;
}

void* btrc_test_realloc(void* pointer, size_t size) {
    if (!pointer) return btrc_test_malloc(size);
    if (size == 0) {
        btrc_test_free(pointer);
        return NULL;
    }

    (void)pthread_mutex_lock(&allocation_lock);
    int index = allocation_index(pointer);
    void* replacement = realloc(pointer, size);
    if (replacement) {
        if (index >= 0) {
            allocations[index] = replacement;
        } else {
            record_allocation(replacement);
        }
    }
    (void)pthread_mutex_unlock(&allocation_lock);
    return replacement;
}

void btrc_test_free(void* pointer) {
    if (!pointer) return;
    (void)pthread_mutex_lock(&allocation_lock);
    int index = allocation_index(pointer);
    if (index >= 0) {
        allocations[index] = NULL;
        allocation_count--;
    }
    (void)pthread_mutex_unlock(&allocation_lock);
    free(pointer);
}

void arc_test_allocation_checkpoint(void) {
    (void)pthread_mutex_lock(&allocation_lock);
    allocation_checkpoint = allocation_count;
    (void)pthread_mutex_unlock(&allocation_lock);
}

long arc_test_allocation_delta(void) {
    (void)pthread_mutex_lock(&allocation_lock);
    long delta = allocation_count - allocation_checkpoint;
    (void)pthread_mutex_unlock(&allocation_lock);
    return delta;
}
