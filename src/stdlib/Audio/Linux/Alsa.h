/* ALSA PCM access for the Linux audio provider. Enum-typed setters, the
 * hint list's triple pointer and the scheduler call stay behind these plain
 * adapters; device policy lives in AlsaDevice.btrc. */
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
/* pcm.h declares a zero-length array that strict C11 rejects. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <alsa/asoundlib.h>
#pragma GCC diagnostic pop
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <string.h>

/* Probing PCMs that another server holds logs slave-open failures; the
 * provider reports availability itself, so the library stays quiet. */
static void btrcAlsaSilentError(const char* file, int line, const char* function, int error, const char* format, ...) {
	(void)file; (void)line; (void)function; (void)error; (void)format;
}

static inline void btrcAlsaQuietErrors(void) { snd_lib_error_set_handler(btrcAlsaSilentError); }

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

static inline void** btrcAlsaHints(void) {
	void** hints = NULL;
	if (snd_device_name_hint(-1, "pcm", &hints) != 0) { return NULL; }
	return hints;
}

static inline int btrcAlsaHintCount(void** hints) {
	int count = 0;
	while (hints != NULL && hints[count] != NULL) { count++; }
	return count;
}

/* A malloc'd hint value, or NULL; free it with btrcAlsaFreeText. */
static inline char* btrcAlsaHintValue(void** hints, int index, const char* key) { return snd_device_name_get_hint(hints[index], key); }

static inline void btrcAlsaFreeText(char* text) { free(text); }

static inline void btrcAlsaHintsFree(void** hints) { snd_device_name_free_hint(hints); }

static inline int btrcAlsaOpen(const char* name, int capture, int nonblocking, snd_pcm_t** out) {
	return snd_pcm_open(out, name, capture ? SND_PCM_STREAM_CAPTURE : SND_PCM_STREAM_PLAYBACK, nonblocking ? SND_PCM_NONBLOCK : 0);
}

static inline int btrcAlsaSetInterleavedFloat(snd_pcm_t* pcm, snd_pcm_hw_params_t* params) {
	int status = snd_pcm_hw_params_set_access(pcm, params, SND_PCM_ACCESS_RW_INTERLEAVED);
	if (status != 0) { return status; }
	return snd_pcm_hw_params_set_format(pcm, params, SND_PCM_FORMAT_FLOAT);
}

static inline int btrcAlsaState(snd_pcm_t* pcm) { return (int)snd_pcm_state(pcm); }

static inline int btrcAlsaStateRunning(void) { return (int)SND_PCM_STATE_RUNNING; }

static inline int btrcAlsaStatePrepared(void) { return (int)SND_PCM_STATE_PREPARED; }

static inline int btrcAlsaPipeError(void) { return -EPIPE; }

static inline int btrcAlsaBusyError(void) { return -EBUSY; }

static inline int btrcAlsaAgainError(void) { return -EAGAIN; }

static inline int btrcAlsaStrandedError(void) { return -ESTRPIPE; }
