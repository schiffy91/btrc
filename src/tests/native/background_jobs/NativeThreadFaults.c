#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>

enum { MUTEX_INIT, COND_INIT, CREATE, JOIN, MUTEX_DESTROY, COND_DESTROY, OP_COUNT };
static int failures[OP_COUNT];
static int calls[OP_COUNT];
static int live_threads;
static int live_mutexes;
static int live_conditions;
static atomic_int disposals;

void job_fault_reset(void) {
    assert(live_threads == 0 && live_mutexes == 0 && live_conditions == 0);
    for (int index = 0; index < OP_COUNT; index++) {
        failures[index] = 0;
        calls[index] = 0;
    }
    atomic_store(&disposals, 0);
}

void job_fault_at(int operation, int call) {
    assert(operation >= 0 && operation < OP_COUNT);
    failures[operation] = call;
}

int job_fault_calls(int operation) {
    assert(operation >= 0 && operation < OP_COUNT);
    return calls[operation];
}

int job_fault_live_threads(void) { return live_threads; }
int job_fault_disposals(void) { return atomic_load(&disposals); }
void job_fault_dispose(void) { atomic_fetch_add(&disposals, 1); }

static int fail(int operation) { return ++calls[operation] == failures[operation]; }

int job_fault_mutex_init(pthread_mutex_t *mutex, const pthread_mutexattr_t *attr) {
    if (fail(MUTEX_INIT)) return EAGAIN;
    int result = pthread_mutex_init(mutex, attr);
    if (result == 0) live_mutexes++;
    return result;
}

int job_fault_cond_init(pthread_cond_t *condition, const pthread_condattr_t *attr) {
    if (fail(COND_INIT)) return EAGAIN;
    int result = pthread_cond_init(condition, attr);
    if (result == 0) live_conditions++;
    return result;
}

int job_fault_create(pthread_t *thread, const pthread_attr_t *attr, void *(*entry)(void *), void *context) {
    if (fail(CREATE)) return EAGAIN;
    int result = pthread_create(thread, attr, entry, context);
    if (result == 0) live_threads++;
    return result;
}

int job_fault_join(pthread_t thread, void **result) {
    if (fail(JOIN)) return EBUSY;
    int status = pthread_join(thread, result);
    if (status == 0) live_threads--;
    return status;
}

int job_fault_mutex_destroy(pthread_mutex_t *mutex) {
    if (fail(MUTEX_DESTROY)) return EBUSY;
    int status = pthread_mutex_destroy(mutex);
    if (status == 0) live_mutexes--;
    return status;
}

int job_fault_cond_destroy(pthread_cond_t *condition) {
    if (fail(COND_DESTROY)) return EBUSY;
    int status = pthread_cond_destroy(condition);
    if (status == 0) live_conditions--;
    return status;
}
