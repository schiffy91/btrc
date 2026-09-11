#pragma once

#include <errno.h>

#ifndef LOCK_EX
#define LOCK_EX 2
#endif
#ifndef LOCK_NB
#define LOCK_NB 4
#endif
#ifndef LOCK_UN
#define LOCK_UN 8
#endif

static inline int flock(int descriptor, int operation) {
    (void)descriptor;
    (void)operation;
    errno = ENOTSUP;
    return -1;
}
