/* SDK-shaped fault injection only. Production ownership/render code is BTRC. */
#define BTRC_ALSA_FAULT_IMPLEMENTATION
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include "AlsaFaults.h"
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { HANDLES = 8, STATE_OPEN = 0, STATE_SETUP = 1, STATE_PREPARED = 2, STATE_RUNNING = 3 };

struct FakePcm { bool used, capture, nonblocking; int state; unsigned int channels, rate; snd_pcm_uframes_t period; };
struct FakeHw { struct FakePcm* pcm; unsigned int channels, rate; snd_pcm_uframes_t period; };

static struct FakePcm handles[HANDLES];
static const char* hint_names[] = {"default", "hw:0,0", "dmix:0"};
static int failure, disposals, stops, renders, input_channels = 2, output_channels = 2;

static struct FakePcm* handle(snd_pcm_t* pcm) {
    struct FakePcm* fake = (struct FakePcm*)pcm;
    assert(fake >= handles && fake < handles + HANDLES && fake->used);
    return fake;
}
static struct FakeHw* hardware(const snd_pcm_hw_params_t* params) { assert(params); return (struct FakeHw*)params; }

void unitReset(int requested) {
    assert(pendingSessions() == 0);
    for (int index = 0; index < HANDLES; index++) { assert(!handles[index].used); }
    failure = requested;
    disposals = stops = renders = 0;
}
void unitFail(int requested) { failure = requested; }
void allowSessionCleanup(void) { failure = 0; }
/* Sessions open their PCMs blocking; probes open nonblocking and close at once. */
int pendingSessions(void) {
    int count = 0;
    for (int index = 0; index < HANDLES; index++) { if (handles[index].used && !handles[index].nonblocking && !handles[index].capture) { count++; } }
    return count;
}
int unitDisposals(void) { return disposals; }
int unitStops(void) { return stops; }
int unitRenders(void) { return renders; }
int unitInputChannels(void) { return input_channels; }
int unitOutputChannels(void) { return output_channels; }
void unitDeviceChannels(int input, int output) { input_channels = input; output_channels = output; }

int alsaFaultHint(int card, const char* iface, void*** hints) {
    assert(card == -1 && strcmp(iface, "pcm") == 0 && hints);
    if (failure == 1) { *hints = NULL; return -ENOENT; }
    void** list = calloc(4, sizeof(void*));
    assert(list);
    for (int index = 0; index < 3; index++) { list[index] = (void*)hint_names[index]; }
    *hints = list;
    return 0;
}
char* alsaFaultHintValue(const void* hint, const char* id) {
    assert(hint && id);
    if (strcmp(id, "NAME") == 0) { return strdup((const char*)hint); }
    if (strcmp(id, "DESC") == 0) { return strcmp((const char*)hint, "default") == 0 ? strdup("Default ALSA Output\nfixture") : NULL; }
    return NULL;
}
int alsaFaultHintFree(void** hints) { free(hints); return 0; }

int alsaFaultOpen(snd_pcm_t** pcm, const char* name, snd_pcm_stream_t stream, int mode) {
    assert(pcm && name);
    *pcm = NULL;
    bool capture = stream == SND_PCM_STREAM_CAPTURE;
    bool nonblocking = (mode & SND_PCM_NONBLOCK) != 0;
    if (strcmp(name, "default") != 0) { return -ENOENT; }
    if (capture && input_channels == 0) { return -ENOENT; }
    if (!capture && output_channels == 0) { return -ENOENT; }
    if (!nonblocking && failure == 2) { return -EBUSY; }
    for (int index = 0; index < HANDLES; index++) {
        if (handles[index].used) { continue; }
        handles[index] = (struct FakePcm){true, capture, nonblocking, STATE_OPEN, 0u, 0u, 0UL};
        *pcm = (snd_pcm_t*)&handles[index];
        return 0;
    }
    return -ENOMEM;
}
int alsaFaultClose(snd_pcm_t* pcm) {
    struct FakePcm* fake = handle(pcm);
    if (!fake->nonblocking) { disposals++; }
    /* alsa-lib frees the handle whether or not the device close succeeds. */
    fake->used = false;
    return !fake->nonblocking && (failure == 10 || failure == 12) ? -EIO : 0;
}

int alsaFaultHwMalloc(snd_pcm_hw_params_t** params) { assert(params); *params = calloc(1, sizeof(struct FakeHw)); return *params ? 0 : -ENOMEM; }
void alsaFaultHwFree(snd_pcm_hw_params_t* params) { free(params); }
int alsaFaultHwAny(snd_pcm_t* pcm, snd_pcm_hw_params_t* params) {
    struct FakeHw* hw = hardware(params);
    hw->pcm = handle(pcm);
    hw->channels = hw->pcm->capture ? (unsigned int)input_channels : (unsigned int)output_channels;
    hw->rate = 48000u;
    hw->period = 256UL;
    return 0;
}
int alsaFaultHwSetAccess(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, snd_pcm_access_t access) { assert(hardware(params)->pcm == handle(pcm)); return access == SND_PCM_ACCESS_RW_INTERLEAVED ? 0 : -EINVAL; }
int alsaFaultHwSetFormat(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, snd_pcm_format_t format) { assert(hardware(params)->pcm == handle(pcm)); return format == SND_PCM_FORMAT_FLOAT ? 0 : -EINVAL; }
int alsaFaultHwSetChannels(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, unsigned int channels) {
    struct FakeHw* hw = hardware(params);
    assert(hw->pcm == handle(pcm));
    unsigned int maximum = hw->pcm->capture ? (unsigned int)input_channels : (unsigned int)output_channels;
    if (channels == 0u || channels > maximum) { return -EINVAL; }
    hw->channels = channels;
    return 0;
}
int alsaFaultHwSetRate(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, unsigned int rate, int direction) {
    struct FakeHw* hw = hardware(params);
    assert(hw->pcm == handle(pcm) && direction == 0);
    if (rate < 8000u || rate > 192000u) { return -EINVAL; }
    hw->rate = rate;
    return 0;
}
int alsaFaultHwSetPeriodSizeNear(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, snd_pcm_uframes_t* frames, int* direction) {
    struct FakeHw* hw = hardware(params);
    assert(hw->pcm == handle(pcm) && frames && direction);
    if (*frames < 16UL || *frames > 65536UL) { return -EINVAL; }
    hw->period = *frames;
    return 0;
}
int alsaFaultHwSetPeriodsNear(snd_pcm_t* pcm, snd_pcm_hw_params_t* params, unsigned int* periods, int* direction) { assert(hardware(params)->pcm == handle(pcm) && periods && direction); return *periods >= 2u ? 0 : -EINVAL; }
int alsaFaultHwGetChannels(const snd_pcm_hw_params_t* params, unsigned int* channels) { *channels = hardware(params)->channels; return 0; }
int alsaFaultHwGetChannelsMax(const snd_pcm_hw_params_t* params, unsigned int* channels) { struct FakeHw* hw = hardware(params); *channels = hw->pcm->capture ? (unsigned int)input_channels : (unsigned int)output_channels; return 0; }
int alsaFaultHwGetRateMin(const snd_pcm_hw_params_t* params, unsigned int* rate, int* direction) { assert(hardware(params)); *rate = 8000u; *direction = 0; return 0; }
int alsaFaultHwGetRateMax(const snd_pcm_hw_params_t* params, unsigned int* rate, int* direction) { assert(hardware(params)); *rate = 192000u; *direction = 0; return 0; }
int alsaFaultHwGetPeriodSizeMin(const snd_pcm_hw_params_t* params, snd_pcm_uframes_t* frames, int* direction) { assert(hardware(params)); *frames = 16UL; *direction = 0; return 0; }
int alsaFaultHwGetPeriodSizeMax(const snd_pcm_hw_params_t* params, snd_pcm_uframes_t* frames, int* direction) { assert(hardware(params)); *frames = 65536UL; *direction = 0; return 0; }
int alsaFaultHwParams(snd_pcm_t* pcm, snd_pcm_hw_params_t* params) {
    struct FakeHw* hw = hardware(params);
    struct FakePcm* fake = handle(pcm);
    assert(hw->pcm == fake && fake->state == STATE_OPEN);
    if (failure == 3 || failure == 12) { return -EINVAL; }
    fake->channels = hw->channels;
    fake->rate = hw->rate;
    fake->period = hw->period;
    fake->state = STATE_PREPARED;
    return 0;
}

int alsaFaultSwMalloc(snd_pcm_sw_params_t** params) { assert(params); *params = calloc(1, sizeof(struct FakeHw)); return *params ? 0 : -ENOMEM; }
void alsaFaultSwFree(snd_pcm_sw_params_t* params) { free(params); }
int alsaFaultSwCurrent(snd_pcm_t* pcm, snd_pcm_sw_params_t* params) { assert(params && handle(pcm)->state == STATE_PREPARED); return 0; }
int alsaFaultSwSetAvailMin(snd_pcm_t* pcm, snd_pcm_sw_params_t* params, snd_pcm_uframes_t frames) { assert(params && frames == handle(pcm)->period); return 0; }
int alsaFaultSwSetStartThreshold(snd_pcm_t* pcm, snd_pcm_sw_params_t* params, snd_pcm_uframes_t frames) { assert(params && frames == handle(pcm)->period); return 0; }
int alsaFaultSwParams(snd_pcm_t* pcm, snd_pcm_sw_params_t* params) { assert(params && handle(pcm)->state == STATE_PREPARED); return 0; }

int alsaFaultPrepare(snd_pcm_t* pcm) {
    struct FakePcm* fake = handle(pcm);
    assert(fake->state != STATE_OPEN);
    if (failure == 7) { return -EIO; }
    fake->state = STATE_PREPARED;
    return 0;
}
int alsaFaultStart(snd_pcm_t* pcm) {
    struct FakePcm* fake = handle(pcm);
    assert(fake->state == STATE_PREPARED);
    if (failure == 20) { return -EIO; }
    fake->state = STATE_RUNNING;
    return 0;
}
int alsaFaultDrop(snd_pcm_t* pcm) {
    struct FakePcm* fake = handle(pcm);
    assert(fake->state != STATE_OPEN);
    stops++;
    if (failure == 9) { return -EBADFD; }
    fake->state = STATE_SETUP;
    return 0;
}
snd_pcm_state_t alsaFaultState(snd_pcm_t* pcm) {
    switch (handle(pcm)->state) {
    case STATE_SETUP: return SND_PCM_STATE_SETUP;
    case STATE_PREPARED: return SND_PCM_STATE_PREPARED;
    case STATE_RUNNING: return SND_PCM_STATE_RUNNING;
    default: return SND_PCM_STATE_OPEN;
    }
}
static void pace(struct FakePcm* fake, snd_pcm_uframes_t frames) {
    struct timespec pause = {0, (long)(frames * 1000000000ULL / (fake->rate ? fake->rate : 48000u))};
    nanosleep(&pause, NULL);
}
snd_pcm_sframes_t alsaFaultWrite(snd_pcm_t* pcm, const void* buffer, snd_pcm_uframes_t frames) {
    struct FakePcm* fake = handle(pcm);
    assert(buffer && !fake->capture && fake->state >= STATE_PREPARED && frames == fake->period);
    const float* samples = buffer;
    for (snd_pcm_uframes_t index = 0; index < frames * fake->channels; index++) { assert(samples[index] == samples[index]); }
    fake->state = STATE_RUNNING;
    renders++;
    pace(fake, frames);
    return (snd_pcm_sframes_t)frames;
}
snd_pcm_sframes_t alsaFaultRead(snd_pcm_t* pcm, void* buffer, snd_pcm_uframes_t frames) {
    struct FakePcm* fake = handle(pcm);
    assert(buffer && fake->capture && fake->state == STATE_RUNNING && frames == fake->period);
    float* samples = buffer;
    for (snd_pcm_uframes_t index = 0; index < frames * fake->channels; index++) { samples[index] = 0.25f; }
    return (snd_pcm_sframes_t)frames;
}
int alsaFaultRecover(snd_pcm_t* pcm, int error, int silent) { handle(pcm); (void)silent; return error == -EPIPE || error == -ESTRPIPE ? 0 : error; }
int alsaFaultErrorHandler(snd_lib_error_handler_t handler) { assert(handler); return 0; }
