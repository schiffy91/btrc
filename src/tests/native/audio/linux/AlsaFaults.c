#define BTRC_ALSA_FAULT_IMPLEMENTATION
#include "AlsaFaults.h"
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <sound/asound.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>

enum { FIRST_FD = 8096, HANDLES = 4 };
struct FakePcm {
    bool used, capture, configured;
    int state;
    unsigned channels, rate, period;
};
static struct FakePcm handles[HANDLES];
static atomic_int failure, renders, reads, waits, stops;
static int disposals, fixed_channels, exclusive, input_channels = 2, output_channels = 2;
static int configured[2];

static int fail(int error) { errno = error; return -1; }
static struct FakePcm* handle(int fd) {
    if (fd < FIRST_FD || fd >= FIRST_FD + HANDLES) { return NULL; }
    assert(handles[fd - FIRST_FD].used);
    return &handles[fd - FIRST_FD];
}

void unitReset(int requested) {
    for (int i = 0; i < HANDLES; i++) { assert(!handles[i].used); }
    failure = requested;
    disposals = 0; stops = 0; renders = 0; reads = 0; waits = 0;
    fixed_channels = exclusive = configured[0] = configured[1] = 0;
}
void unitFail(int requested) { failure = requested; }
void allowSessionCleanup(void) { failure = 0; }
int pendingSessions(void) {
    int count = 0;
    for (int i = 0; i < HANDLES; i++) {
        if (handles[i].used && handles[i].configured && !handles[i].capture) { count++; }
    }
    return count;
}
int unitDisposals(void) { return disposals; }
int unitStops(void) { return stops; }
int unitRenders(void) { return renders; }
int unitReads(void) { return reads; }
void unitDeviceChannels(int input, int output) { input_channels = input; output_channels = output; }
void unitFixedChannels(int fixed) { fixed_channels = fixed; }
int unitConfiguredChannels(int capture) { return configured[capture != 0]; }
void unitExclusive(int hold) { exclusive = hold; }

FILE* alsaFaultFile(const char* path, const char* mode) {
    static char list[] = "00-00: Test PCM : test : playback 1 : capture 1\n";
    static char id[] = "TestCard\n";
    if (!strcmp(path, "/proc/asound/pcm")) {
        if (failure == 1) { errno = ENOENT; return NULL; }
        return fmemopen(list, strlen(list), "r");
    }
    if (!strcmp(path, "/proc/asound/card0/id")) { return fmemopen(id, strlen(id), "r"); }
    return fopen(path, mode);
}

int alsaFaultOpen(const char* path, int flags, ...) {
    bool capture = !strcmp(path, "/dev/snd/pcmC0D0c");
    if (!capture && strcmp(path, "/dev/snd/pcmC0D0p")) {
        if (!(flags & O_CREAT)) { return open(path, flags); }
        va_list args; va_start(args, flags); int mode = va_arg(args, int); va_end(args);
        return open(path, flags, mode);
    }
    assert(flags & O_NONBLOCK);
    if ((capture ? input_channels : output_channels) == 0) { return fail(ENOENT); }
    for (int i = 0; i < HANDLES; i++) {
        if (exclusive && handles[i].used && handles[i].capture == capture) { return fail(EBUSY); }
    }
    for (int i = 0; i < HANDLES; i++) {
        if (!handles[i].used) {
            handles[i] = (struct FakePcm){.used=true, .capture=capture, .state=SNDRV_PCM_STATE_OPEN};
            return FIRST_FD + i;
        }
    }
    return fail(ENOMEM);
}

int alsaFaultClose(int fd) {
    struct FakePcm* pcm = handle(fd);
    if (!pcm) { return close(fd); }
    if (pcm->configured) { disposals++; }
    pcm->used = false;
    return pcm->configured && (failure == 10 || failure == 12) ? fail(EIO) : 0;
}

static struct snd_interval* interval(struct snd_pcm_hw_params* p, int field) {
    return &p->intervals[field - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
}
static bool intersect(struct snd_pcm_hw_params* p, int field, unsigned min, unsigned max) {
    struct snd_interval* i = interval(p, field);
    if (i->min < min) { i->min = min; }
    if (i->max > max) { i->max = max; }
    return i->min <= i->max;
}

static int refine(struct FakePcm* pcm, struct snd_pcm_hw_params* p) {
    unsigned maximum = (unsigned)(pcm->capture ? input_channels : output_channels);
    if (p->masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[0] != UINT_MAX) {
        pcm->configured = true;
        if (failure == 2) { return fail(EBUSY); }
        if (!(p->masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[0] & (1u << SNDRV_PCM_FORMAT_FLOAT_LE))) { return fail(EINVAL); }
    }
    if (!intersect(p, SNDRV_PCM_HW_PARAM_CHANNELS, fixed_channels ? (unsigned)fixed_channels : 1u, maximum) ||
        !intersect(p, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, 16, 65536) ||
        !intersect(p, SNDRV_PCM_HW_PARAM_RATE, 8000, 192000) ||
        !intersect(p, SNDRV_PCM_HW_PARAM_PERIODS, 2, 8)) { return fail(EINVAL); }
    return 0;
}

static int transfer(struct FakePcm* pcm, struct snd_xferi* xfer, bool capture) {
    assert(xfer->buf && xfer->frames == pcm->period && capture == pcm->capture);
    float* samples = xfer->buf;
    if (capture) {
        assert(pcm->state == SNDRV_PCM_STATE_RUNNING);
        if (failure == 25) { failure = 0; pcm->state = SNDRV_PCM_STATE_XRUN; return fail(EPIPE); }
        if (failure == 26) { failure = 0; pcm->state = SNDRV_PCM_STATE_SUSPENDED; return fail(ESTRPIPE); }
        if (failure == 27) { failure = 0; return fail(EINTR); }
        for (unsigned i = 0; i < pcm->period * pcm->channels; i++) { samples[i] = 0.25f; }
        reads++;
    } else {
        assert(pcm->state == SNDRV_PCM_STATE_RUNNING || pcm->state == SNDRV_PCM_STATE_PREPARED);
        if (failure == 21 && pcm->state == SNDRV_PCM_STATE_RUNNING) { return fail(ENODEV); }
        if (failure == 24) { return fail(EIO); }
        for (unsigned i = 0; i < pcm->period * pcm->channels; i++) { assert(samples[i] == samples[i]); }
        pcm->state = SNDRV_PCM_STATE_RUNNING;
        renders++;
        struct timespec pause = {0,(long)((unsigned long long)pcm->period * 1000000000ULL / pcm->rate)};
        nanosleep(&pause, NULL);
    }
    xfer->result = (snd_pcm_sframes_t)xfer->frames;
    return 0;
}

int alsaFaultIoctl(int fd, unsigned long request, ...) {
    struct FakePcm* pcm = handle(fd);
    assert(pcm);
    va_list args;
    va_start(args, request);
    void* argument = _IOC_DIR(request) != _IOC_NONE ? va_arg(args, void*) : NULL;
    va_end(args);
    switch (request) {
    case SNDRV_PCM_IOCTL_HW_REFINE: return refine(pcm, argument);
    case SNDRV_PCM_IOCTL_HW_PARAMS: {
        struct snd_pcm_hw_params* p = argument;
        if (failure == 3 || failure == 12) { return fail(EINVAL); }
        pcm->channels = interval(p, SNDRV_PCM_HW_PARAM_CHANNELS)->min;
        pcm->rate = interval(p, SNDRV_PCM_HW_PARAM_RATE)->min;
        pcm->period = interval(p, SNDRV_PCM_HW_PARAM_PERIOD_SIZE)->min;
        configured[pcm->capture] = (int)pcm->channels;
        interval(p, SNDRV_PCM_HW_PARAM_BUFFER_SIZE)->min = pcm->period * 2;
        pcm->state = SNDRV_PCM_STATE_SETUP;
        return 0;
    }
    case SNDRV_PCM_IOCTL_SW_PARAMS: {
        struct snd_pcm_sw_params* p = argument;
        assert(p->start_threshold == pcm->period && p->avail_min == pcm->period);
        return 0;
    }
    case SNDRV_PCM_IOCTL_PREPARE:
        if (failure == 7) { return fail(EIO); }
        pcm->state = SNDRV_PCM_STATE_PREPARED; return 0;
    case SNDRV_PCM_IOCTL_START:
        if (failure == 20) { return fail(EIO); }
        if (pcm->state != SNDRV_PCM_STATE_PREPARED) { return fail(EBADFD); }
        pcm->state = SNDRV_PCM_STATE_RUNNING; return 0;
    case SNDRV_PCM_IOCTL_DROP:
        stops++;
        if (failure == 9) { return fail(EBADFD); }
        pcm->state = SNDRV_PCM_STATE_SETUP; return 0;
    case SNDRV_PCM_IOCTL_RESUME:
        if (pcm->state != SNDRV_PCM_STATE_SUSPENDED) { return fail(EBADFD); }
        pcm->state = SNDRV_PCM_STATE_RUNNING; return 0;
    case SNDRV_PCM_IOCTL_STATUS:
        ((struct snd_pcm_status*)argument)->state = pcm->state; return 0;
    case SNDRV_PCM_IOCTL_READI_FRAMES:
    case SNDRV_PCM_IOCTL_WRITEI_FRAMES:
        return transfer(pcm, argument, request == SNDRV_PCM_IOCTL_READI_FRAMES);
    default: assert(!"unexpected PCM ioctl"); return fail(EINVAL);
    }
}

int alsaFaultPoll(struct pollfd* fds, nfds_t count, int timeout) {
    if (count != 1 || !handle(fds[0].fd)) { return poll(fds,count,timeout); }
    assert(timeout > 0);
    if (failure == 22 || (failure == 23 && waits++ == 0)) {
        struct timespec pause = {failure == 23 ? 6 : 0, failure == 23 ? 0L : (long)timeout * 1000000L};
        nanosleep(&pause,NULL);
        return failure == 23 ? 1 : 0;
    }
    fds[0].revents = fds[0].events;
    return 1;
}
