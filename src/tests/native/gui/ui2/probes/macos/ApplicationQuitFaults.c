#include "ApplicationQuitFaults.h"
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

/* Executable-local test symbol: only the explicitly armed calling thread and
 * its first actual try-lock identity receive the injected native return code. */
static _Thread_local bool armed;
static _Thread_local pthread_mutex_t *target;
static _Thread_local int faults;

int pthread_mutex_trylock(pthread_mutex_t *mutex) {
    if (armed && (target == NULL || target == mutex)) {
        target = mutex;
        faults++;
        return EINVAL;
    }
    void *symbol = dlsym(RTLD_NEXT, "pthread_mutex_trylock");
    int (*original)(pthread_mutex_t *) = NULL;
    _Static_assert(sizeof(original) == sizeof(symbol), "POSIX function pointer representation");
    memcpy(&original, &symbol, sizeof(original));
    if (original == NULL || original == pthread_mutex_trylock) {
        abort();
    }
    return original(mutex);
}

bool ui2ArmQuitPublisherFault(void) {
    if (armed || target != NULL) {
        return false;
    }
    faults = 0;
    armed = true;
    return true;
}

void ui2DisarmQuitPublisherFault(void) {
    armed = false;
    target = NULL;
}

int ui2QuitPublisherFaultCount(void) {
    return faults;
}
