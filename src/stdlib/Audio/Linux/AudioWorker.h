#ifndef BTRC_AUDIO_LINUX_AUDIO_WORKER_H
#define BTRC_AUDIO_LINUX_AUDIO_WORKER_H
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "LegacyPcm.h"
#include "ConfiguredPcm.h"
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <string.h>

static inline unsigned long long btrcAlsaHostNanoseconds(void) {
	struct timespec now;
	if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) { return 0ULL; }
	return (unsigned long long)now.tv_sec * 1000000000ULL + (unsigned long long)now.tv_nsec;
}

/* Best-effort realtime scheduling for the calling thread; failures are silent. */
static inline int btrcAlsaRealtimePriority(void) {
	struct sched_param parameters;
	memset(&parameters, 0, sizeof(parameters));
	int maximum = sched_get_priority_max(SCHED_FIFO);
	parameters.sched_priority = maximum > 70 ? 70 : maximum;
	return pthread_setschedparam(pthread_self(), SCHED_FIFO, &parameters) == 0 ? 1 : 0;
}

#endif
